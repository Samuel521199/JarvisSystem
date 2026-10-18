"""Conversation links must not rebind, execute archives, or replay tasks."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
from jarvis_core.service import CoreService
from jarvis_core.conversation_tasks import ConversationTasks
from jarvis_core.conversations import ConversationStore, ConversationError, validate_document
from jarvis_core.policy import CoreError
from jarvis_computer.web import ComputerWeb
from test_sample_tasks import SyntheticPlanner
from test_web import FakeChat
from test_conversations import document


class ConversationTaskTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);source=self.root/'sample';source.mkdir();(source/'a.txt').write_bytes(b'abc')
        self.core=CoreService(self.root/'data');self.core.initialize(source)
        self.manager=ComputerWeb(self.core,FakeChat());self.addCleanup(self.manager.close)
        self.manager.queue.set_paused(True)
        self.planner=SyntheticPlanner();self.manager.sample.chat_factory=lambda *a,**kw:self.planner
        self.bridge=ConversationTasks(self.core,self.manager)
        self.first=uuid.uuid4().hex;self.other=uuid.uuid4().hex
        self.payload={'request_id':'web-'+uuid.uuid4().hex,'prompt':'列举样例并统计保存报告','model':'auto'}

    def submit(self,cid=None,payload=None):return self.bridge.submit(cid or self.first,payload or self.payload)

    def wait(self,item):
        end=time.monotonic()+10
        while time.monotonic()<end:
            data=self.bridge.detail(self.first,item['task_id'])
            if data['task']['status'] not in {'READY','RUNNING','CANCELLING'}:return data
            time.sleep(.02)
        self.fail('Task did not finish')

    def test_association_is_atomic_and_part_of_idempotence(self):
        item=self.submit();self.assertEqual(self.submit(),item)
        self.assertEqual(self.core.ledger.record(task_id=item['task_id'])['action']['arguments']['conversation_id'],self.first)
        with self.assertRaises(CoreError):self.submit(self.other)
        with self.assertRaises(CoreError):self.submit(payload={**self.payload,'prompt':'different'})
        self.assertEqual([r['task_id'] for r in self.bridge.list(self.first)['tasks']],[item['task_id']])
        self.assertEqual(self.bridge.list(self.other)['tasks'],[])
        self.assertEqual(self.planner.calls,[])

    def test_cross_conversation_detail_lookup_cancel_and_artifact_rejected(self):
        item=self.submit()
        for call in (lambda:self.bridge.detail(self.other,item['task_id']),
                     lambda:self.bridge.lookup(self.other,self.payload['request_id']),
                     lambda:self.bridge.cancel(self.other,item['task_id'],{}),
                     lambda:self.bridge.artifact(self.other,item['task_id'])):
            with self.assertRaises(CoreError) as e:call()
            self.assertEqual(e.exception.code,'not_found')
        self.assertFalse(self.core.ledger.record(task_id=item['task_id'])['cancel_requested'])

    def test_conversation_filter_precedes_recent_thirty_limit(self):
        item=self.submit()
        for _ in range(31):
            other=self.submit(self.other,{**self.payload,'request_id':'web-'+uuid.uuid4().hex})
            self.bridge.cancel(self.other,other['task_id'],{})
        self.assertEqual([r['task_id'] for r in self.bridge.list(self.first)['tasks']],[item['task_id']])
        self.assertEqual(len(self.bridge.list(self.other)['tasks']),30)

    def test_global_task_cannot_be_attached_after_acceptance(self):
        item=self.manager.submit_task({**self.payload,'mode':'natural'})
        self.assertEqual(self.bridge.list(self.first)['tasks'],[])
        with self.assertRaises(CoreError):self.submit()
        with self.assertRaises(CoreError):self.bridge.detail(self.first,item['task_id'])

    def test_restart_restores_link_without_archive_or_model_call(self):
        item=self.submit();self.manager.close()
        self.manager=ComputerWeb(self.core,FakeChat());self.addCleanup(self.manager.close)
        bridge=ConversationTasks(self.core,self.manager)
        self.assertTrue(self.manager.queue.snapshot()['paused'])
        self.assertEqual(bridge.lookup(self.first,self.payload['request_id'])['task']['task_id'],item['task_id'])
        self.assertEqual(bridge.list(self.first)['tasks'][0]['task_id'],item['task_id'])
        self.assertFalse((self.core.data_dir/'conversations.db').exists())

    def test_real_report_download_is_exact_committed_bytes_and_damage_visible(self):
        item=self.submit();self.manager.queue.set_paused(False);data=self.wait(item)
        self.assertEqual(data['task']['status'],'SUCCEEDED')
        raw=self.bridge.artifact(self.first,item['task_id'])
        self.assertEqual('sha256:'+hashlib.sha256(raw).hexdigest(),data['artifact']['digest'])
        self.assertEqual(json.loads(raw)['total_bytes'],3)
        prompt=self.planner.calls[0][0];self.assertNotIn(self.first,prompt)
        self.assertNotIn(str(self.root),prompt)
        path=Path(data['artifact_path']);path.write_bytes(b'damaged')
        with self.assertRaises(CoreError):self.bridge.artifact(self.first,item['task_id'])
        with self.assertRaises(CoreError):self.bridge.detail(self.first,item['task_id'])
        # Receipt lookup still proves admission, without claiming the file is valid.
        self.assertEqual(self.bridge.lookup(self.first,self.payload['request_id'])['task']['status'],'SUCCEEDED')
        self.assertEqual(len(self.planner.calls),1)

    def test_cancel_after_stop_and_delete_archive_preserve_task_audit(self):
        item=self.submit();archive=ConversationStore(self.core)
        archive.put(self.first,{'revision':0,'document':document()})
        archive.delete(self.first,{'revision':1})
        self.assertEqual(self.bridge.list(self.first)['tasks'][0]['task_id'],item['task_id'])
        self.core.stop('temporary test')
        data=self.bridge.cancel(self.first,item['task_id'],{})
        self.assertEqual(data['task']['status'],'CANCELLED')
        self.assertTrue(self.core.ledger.control()['stopped'])

    def test_unknown_fields_and_bad_identifiers_never_create_task(self):
        for payload in ({**self.payload,'history':[]},{**self.payload,'conversation_id':self.other},
                        {**self.payload,'mode':'inventory'},{**self.payload,'relative_path':'../'}):
            with self.assertRaises(CoreError):self.submit(payload=payload)
        for value in ('../',[], 'a'*31):
            with self.assertRaises(CoreError):self.bridge.list(value)
        self.assertEqual(self.core.status()['tasks'],[])


class ArchiveTaskLinkTests(unittest.TestCase):
    def test_optional_markers_roundtrip_and_invalid_links_rejected(self):
        doc=document();row=doc['messages'][0]
        row.update(task_control=True,task_ref='task_'+'a'*32,task_request_id='web-'+'b'*32)
        encoded,_,_=validate_document(doc);self.assertEqual(json.loads(encoded),doc)
        for changes in ({'task_control':'true'},{'task_ref':'javascript:alert(1)'},
                        {'task_request_id':'../'},{'task_control':False}):
            invalid=deepcopy(doc);invalid['messages'][0].update(changes)
            with self.assertRaises(ConversationError):validate_document(invalid)


class ConversationTaskHTTPTests(unittest.TestCase):
    def setUp(self):
        import test_computer_web as helpers
        self.fixture=helpers.ComputerWebTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.manager.queue.set_paused(True)
        self.fixture.server.conversation_tasks=ConversationTasks(self.fixture.core,self.fixture.manager)
        self.id=uuid.uuid4().hex;self.path='/api/conversation-tasks/'+self.id
        self.payload={'request_id':'web-'+uuid.uuid4().hex,'prompt':'统计并保存样例目录','model':'auto'}

    def test_nonce_origin_and_strict_routes(self):
        f=self.fixture
        self.assertEqual(f.request('GET',self.path)[0],403)
        self.assertEqual(f.request('POST',self.path,self.payload,headers={'X-Jarvis-Nonce':None})[0],403)
        self.assertEqual(f.request('POST',self.path,self.payload,headers={'Origin':'https://evil.test'})[0],403)
        self.assertEqual(f.request('POST',self.path,{**self.payload,'shell':'cmd'})[0],400)
        self.assertEqual(f.get(self.path+'?id=x')[0],404)
        self.assertEqual(f.get(self.path+'/../../private')[0],404)
        self.assertEqual(f.get('/conversation_tasks.js')[0],200)
        self.assertEqual(f.get('/conversation_tasks.js?path=../')[0],404)
        self.assertNotIn(b'__JARVIS_',f.get('/')[2])

    def test_scoped_lookup_cancel_and_duplicate_have_no_model_calls(self):
        f=self.fixture;status,_,raw=f.request('POST',self.path,self.payload)
        self.assertEqual(status,202);item=json.loads(raw)
        self.assertEqual(json.loads(f.request('POST',self.path,self.payload)[2]),item)
        self.assertEqual(json.loads(f.get(self.path)[2])['tasks'][0]['task_id'],item['task_id'])
        self.assertEqual(f.get(self.path+'/requests/'+self.payload['request_id'])[0],200)
        other='/api/conversation-tasks/'+uuid.uuid4().hex+'/'+item['task_id']
        self.assertEqual(f.get(other)[0],404)
        self.assertEqual(f.request('POST',other+'/cancel',{})[0],404)
        self.assertEqual(f.request('POST',self.path+'/'+item['task_id']+'/cancel',{'all':True})[0],400)
        self.assertEqual(f.request('POST',self.path+'/'+item['task_id']+'/cancel',{})[0],200)
        self.assertEqual(f.get(self.path+'/'+item['task_id']+'/artifact')[0],400)
        self.assertEqual(f.chat.calls,[])


if __name__=='__main__':unittest.main()
