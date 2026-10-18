"""Receipt isolation, admission bounds and failure recovery without cloud calls."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import test_web as fixtures


class DialogueTests(unittest.TestCase):
    setUp = fixtures.WebTests.setUp
    request = fixtures.WebTests.request

    def envelope(self, message='hello', **extra):
        return dict(instance_id=self.server.instance_id, conversation_id=uuid.uuid4().hex,
                    request_id=uuid.uuid4().hex, chat={'message':message}, **extra)

    def post(self, value):
        status, _, body = self.request('POST', '/api/dialogue/turns', value)
        return status, json.loads(body)

    def poll(self, value, **headers):
        path='/api/dialogue/turns/'+value['request_id']+'?conversation_id='+value['conversation_id']+'&instance_id='+value['instance_id']
        status, _, body = self.request('GET', path, headers={'X-Jarvis-Nonce':self.server.nonce, **headers})
        return status, json.loads(body)

    def cancel(self, value):
        return self.request('POST', '/api/dialogue/cancel', {k:v for k,v in value.items() if k!='chat'})

    def finished(self, value):
        end=time.monotonic()+3
        while time.monotonic()<end:
            status,result=self.poll(value)
            if result.get('finished'):return result
            time.sleep(.01)
        self.fail('reply never finished')

    def hold(self):
        entered,release=threading.Event(),threading.Event()
        def hook():entered.set();release.wait(3)
        self.chat.hook=hook;self.addCleanup(release.set)
        return entered,release

    def test_admission_does_not_wait_and_repeat_is_idempotent(self):
        entered,release=self.hold();value=self.envelope()
        start=time.monotonic();status,receipt=self.post(value)
        self.assertEqual(status,202);self.assertLess(time.monotonic()-start,.8)
        self.assertTrue(entered.wait(1));self.assertFalse(receipt['finished'])
        self.assertEqual(self.post(value)[0],202);self.assertEqual(len(self.chat.calls),1)
        self.assertEqual(self.post({**value,'chat':{'message':'changed'}})[0],409)
        release.set();final=self.finished(value)
        self.assertEqual(final['status'],'SUCCEEDED');self.assertEqual(self.post(value)[1]['result'],final['result'])
        self.assertEqual(len(self.chat.calls),1)

    def test_query_and_cancel_are_scoped_and_nonce_protected(self):
        entered,release=self.hold();value=self.envelope();self.post(value);self.assertTrue(entered.wait(1))
        self.assertEqual(self.poll(value,**{'X-Jarvis-Nonce':None})[0],403)
        other={**value,'conversation_id':uuid.uuid4().hex}
        self.assertEqual(self.poll(other)[0],404);self.assertEqual(self.cancel(other)[0],404)
        self.assertFalse(self.chat.cancel_event.is_set())
        restarted={**value,'instance_id':uuid.uuid4().hex}
        for operation in (self.post,self.poll,self.cancel):self.assertEqual(operation(restarted)[0],409)
        release.set();self.finished(value)

    def test_same_conversation_serializes_and_legacy_shares_slots(self):
        entered,release=self.hold();value=self.envelope();self.post(value);self.assertTrue(entered.wait(1))
        self.assertEqual(self.post({**value,'request_id':uuid.uuid4().hex})[0],409)
        with ThreadPoolExecutor(1) as pool:
            legacy=pool.submit(self.request,'POST','/api/chat',{'message':'legacy'})
            end=time.monotonic()+1
            while self.server.chat_requests.active<2 and time.monotonic()<end:time.sleep(.005)
            self.assertEqual(self.post(self.envelope())[0],429)
            self.assertEqual(self.request('GET','/api/status')[0],200)
            release.set();self.assertEqual(legacy.result()[0],200)
        self.finished(value);self.assertEqual(self.server.dialogue.snapshot()['active'],0)

    def test_cancel_keeps_slot_until_worker_exits_and_drops_late_output(self):
        entered,release=self.hold();value=self.envelope();self.post(value);self.assertTrue(entered.wait(1))
        self.core.stopped=True
        self.assertEqual(self.cancel(value)[0],200)
        self.assertEqual(self.poll(value)[1]['status'],'CANCELLING')
        self.assertEqual(self.server.chat_requests.active,1)
        release.set();final=self.finished(value)
        self.assertEqual(final['status'],'CANCELLED');self.assertNotIn('text',final['result'])
        self.assertEqual(self.server.chat_requests.active,0)

    def test_cancel_before_admission_never_invokes_model(self):
        value=self.envelope();self.assertEqual(self.cancel(value)[0],200)
        self.assertEqual(self.post(value)[1]['status'],'CANCELLED');self.assertEqual(self.chat.calls,[])

    def test_result_expiration_does_not_allow_replay(self):
        value=self.envelope();self.post(value);self.finished(value)
        self.server.dialogue.RESULT_TTL=-1
        self.assertTrue(self.poll(value)[1]['expired'])
        self.assertNotIn('result',self.post(value)[1]);self.assertEqual(len(self.chat.calls),1)
        self.assertEqual(self.server.dialogue.snapshot()['reserved_bytes'],0)

    def test_id_and_memory_capacity_fail_without_dispatch(self):
        self.server.dialogue.MAX_IDS=1
        first=self.envelope();self.post(first);self.finished(first)
        self.assertEqual(self.post(self.envelope())[0],429)
        self.server.dialogue.MAX_IDS=20;self.server.dialogue.MAX_BYTES=1
        self.assertEqual(self.post(self.envelope())[0],429);self.assertEqual(len(self.chat.calls),1)

    def test_bad_input_and_provider_rejected_before_dispatch(self):
        value=self.envelope()
        for patch_value in ({'chat':{'message':'hi','provider':'nonexistent'}}, {'chat':{'message':'hi','extra':'bad'}}, {'conversation_id':'bad'}, {'extra':'bad'}, {'chat':None}):
            self.assertEqual(self.post({**value,**patch_value})[0],400)
        self.assertEqual(self.chat.calls,[])

    def test_model_error_is_uncertain_sanitized_and_slots_released(self):
        self.chat.hook=lambda:(_ for _ in ()).throw(RuntimeError('secret fixture'))
        value=self.envelope();self.post(value);final=self.finished(value)
        self.assertEqual(final['status'],'UNKNOWN');self.assertNotIn('secret fixture',json.dumps(final))
        self.assertEqual(self.server.chat_requests.active,0)

    def test_thread_creation_failure_and_large_output_release_reservations(self):
        value=self.envelope()
        with patch('jarvis_core.turns.threading.Thread.start',side_effect=RuntimeError('fixture')):
            result=self.server.dialogue.submit(value['instance_id'],value['conversation_id'],value['request_id'],value['chat'])
        self.assertEqual(result['status'],'FAILED');self.assertFalse(result['result']['outcome_uncertain'])
        self.assertEqual(self.server.chat_requests.active,0);self.assertEqual(self.chat.calls,[])
        self.server.dialogue.MAX_RESULT_BYTES=10
        value=self.envelope();self.post(value);self.assertEqual(self.finished(value)['status'],'FAILED')

    def test_personal_commit_not_reported_cancelled(self):
        entered,release=threading.Event(),threading.Event()
        def committed(*a,**kw):entered.set();release.wait(3);return {'status':'SUCCEEDED','text':'saved','personal':{'committed':True}}
        self.chat.reply=committed;value=self.envelope();self.addCleanup(release.set)
        self.post(value);self.assertTrue(entered.wait(1));self.cancel(value);release.set()
        self.assertEqual(self.finished(value)['status'],'SUCCEEDED')


if __name__=='__main__':unittest.main()
