"""Rule facts share signed review, source revocation and atomic revision protection."""
from copy import deepcopy
import json
import time
import unittest
import uuid
from unittest.mock import patch

import test_personal_candidates as fixtures
from jarvis_core.memory import MemoryStore, MemoryError
from jarvis_core.personal_candidates import PersonalCandidates, ENGINE
from jarvis_core.semantic_candidates import SemanticCandidates
from jarvis_core.chat import ChatService
from jarvis_core.candidate_tokens import TTL


class RuleReviewTests(unittest.TestCase):
    setUp=fixtures.CandidateTests.setUp
    payload=fixtures.CandidateTests.payload

    def confirmation(self,preview=None):
        p=preview or self.service.suggest(self.query);item=p['candidates'][0]
        return {'preview_token':p['preview_token'],'candidate_id':item['candidate_id'],'title':item['title'],
            'content':item['content'],'classification':item['classification'],'scope':'current'}

    def seed(self,content='我平时喜欢咖啡',**changes):
        doc={'title':'饮品偏好','content':content,'project_id':None,'providers':['vertex'],
             'classification':self.service.classification()}
        doc.update(changes);return MemoryStore(self.core).put(uuid.uuid4().hex,{'revision':0,'document':doc})

    def error(self,code,call):
        with self.assertRaises(MemoryError) as e:call()
        self.assertEqual(e.exception.code,code)

    def resolve(self,review,decision='new',target=None):
        return self.service.resolve({'review_token':review['review_token'],'decision':decision,'target_id':target})

    def test_preview_review_and_new_save_are_local_without_model(self):
        with patch('jarvis_core.chat.gateway.probe') as model:
            value=self.confirmation();review=self.service.review(value)
            self.assertFalse(MemoryStore(self.core).path.exists())
            self.assertEqual(review['matches'],[])
            result=self.resolve(review);model.assert_not_called()
        self.assertTrue(result['receipt']['committed'])
        row=MemoryStore(self.core).list()['facts'][0]
        self.assertEqual(row['document']['classification']['uses'],['personal_chat'])
        self.assertEqual(row['document']['providers'],[])

    def test_duplicate_keep_does_not_change_permissions_or_fact_revision(self):
        old=self.seed('我平时喜欢无糖茶。')
        review=self.service.review(self.confirmation())
        self.assertEqual(review['matches'][0]['relation'],'duplicate')
        result=self.resolve(review,'keep',old['id'])
        row=MemoryStore(self.core).list()['facts'][0]
        self.assertEqual(row['revision'],old['revision']);self.assertEqual(row['document']['providers'],['vertex'])
        self.assertTrue(self.resolve(review,'keep',old['id'])['receipt']['replayed'])
        self.assertTrue(result['receipt']['committed'])

    def test_explicit_update_preserves_target_policy_and_name(self):
        old=self.seed();review=self.service.review(self.confirmation())
        self.assertEqual(review['matches'][0]['relation'],'related')
        self.resolve(review,'replace',old['id'])
        row=MemoryStore(self.core).list()['facts'][0]
        self.assertEqual(row['document'],old['document']|{'content':'我平时喜欢无糖茶'})
        self.assertEqual(row['revision'],old['revision']+1)

    def test_correction_after_preview_rejects_both_direct_and_review_paths(self):
        old=self.seed();body=self.payload();value=self.confirmation()
        MemoryStore(self.core).command('correct',old['id'],'不喝茶也不喝咖啡',request_id=uuid.uuid4().hex)
        self.error('candidate_review_changed',lambda:self.service.review(value))
        self.error('candidate_review_changed',lambda:self.service.confirm(body))
        self.assertEqual(len(MemoryStore(self.core).list()['facts']),1)

    def test_forget_after_review_never_recreates_even_new_name(self):
        old=self.seed();review=self.service.review(self.confirmation())
        MemoryStore(self.core).delete(old['id'],{'revision':old['revision']})
        self.error('candidate_review_changed',lambda:self.resolve(review))
        self.assertEqual(MemoryStore(self.core).list()['facts'],[])

    def test_revision_changes_during_rule_extraction_refuses_preview(self):
        with patch.object(MemoryStore,'review_revision',side_effect=[0,1]):
            self.error('candidate_review_changed',lambda:self.service.suggest(self.query))
        self.assertFalse(MemoryStore(self.core).path.exists())

    def test_source_deleted_or_changed_after_review_blocks_commit(self):
        review=self.service.review(self.confirmation())
        self.archives.delete(self.cid,{'revision':1})
        with self.assertRaises(MemoryError):self.resolve(review)
        self.assertEqual(MemoryStore(self.core).list()['facts'],[])

    def test_token_tamper_restart_expiry_and_semantic_token_not_accepted(self):
        value=self.confirmation();bad={**value,'preview_token':value['preview_token']+'x'}
        self.error('candidate_preview_expired',lambda:self.service.review(bad))
        self.error('candidate_preview_expired',lambda:PersonalCandidates(self.core).review(value))
        with patch('jarvis_core.candidate_tokens.time.time',return_value=10**12):
            self.error('candidate_preview_expired',lambda:self.service.review(value))
        semantic=SemanticCandidates(self.core,ChatService(self.core))
        self.error('candidate_preview_expired',lambda:semantic.review(value))
        self.assertFalse(MemoryStore(self.core).path.exists())

    def test_unversioned_legacy_preview_cannot_create_fact(self):
        body=self.payload();body.pop('preview_token')
        self.error('candidate_review_required',lambda:self.service.confirm(body))
        self.assertEqual(MemoryStore(self.core).list()['facts'],[])

    def test_legacy_exact_receipt_can_be_replayed_after_forget(self):
        body=self.payload();body.pop('preview_token')
        item=body['candidate'];legacy={**body,'candidate':{k:item[k] for k in ('kind','title','content','next_step')}}
        key=uuid.uuid5(uuid.NAMESPACE_URL,ENGINE+json.dumps(legacy,ensure_ascii=False,sort_keys=True)).hex
        origin={**body['source'],'project_id':None,'sha256':body['source_digest'],
            'candidate_id':item['candidate_id'],'archive_revision':1}
        memory=MemoryStore(self.core)
        first=memory.command('remember',item['title'],item['content'],request_id=key,candidate_source=origin)
        memory.command('forget',first['id'],None,request_id=uuid.uuid4().hex)
        self.assertTrue(PersonalCandidates(self.core).confirm(body)['receipt']['replayed'])
        self.assertEqual(memory.list()['facts'],[])

    def test_stale_token_does_not_prevent_exact_new_style_receipt_replay(self):
        body=self.payload();first=self.service.confirm(body)
        memory=MemoryStore(self.core);memory.command('forget',first['receipt']['id'],None,request_id=uuid.uuid4().hex)
        self.assertTrue(PersonalCandidates(self.core).confirm(body)['receipt']['replayed'])
        changed=deepcopy(body);changed['candidate']['title']='改名重放'
        self.error('candidate_review_required',lambda:PersonalCandidates(self.core).confirm(changed))
        self.assertEqual(memory.list()['facts'],[])

    def test_rule_and_semantic_identity_fences_are_shared(self):
        review=self.service.review(self.confirmation());self.resolve(review)
        self.error('memory_conflict',lambda:self.service.confirm(self.payload()))
        row=MemoryStore(self.core).list()['facts'][0]
        MemoryStore(self.core).delete(row['id'],{'revision':row['revision']})
        self.assertTrue(self.resolve(self.service.review(self.confirmation()))['receipt']['replayed'])
        preview=self.service.suggest(self.query)
        semantic=SemanticCandidates(self.core,ChatService(self.core))
        draft={k:preview[k] for k in ('source','project_id','source_digest','candidates')}
        draft.update(review_revision=MemoryStore(self.core).review_revision(),expires=int(time.time())+TTL)
        payload=self.confirmation(preview)|{'preview_token':semantic.sign(draft),'title':'切换引擎后改名'}
        self.error('candidate_suppressed',lambda:semantic.confirm(payload))
        self.assertEqual(MemoryStore(self.core).list()['facts'],[])

    def test_http_review_resolve_nonce_and_stale_preview(self):
        import http.client
        import threading
        from test_web import web
        server=web.create_server(core=self.core,chat=ChatService(self.core),port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def call(action,payload,nonce=None):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            try:
                connection.request('POST','/api/personal-candidates/'+action,json.dumps(payload),headers={
                    'Content-Type':'application/json','Origin':'http://127.0.0.1:'+str(server.server_port),
                    'X-Jarvis-Nonce':server.nonce if nonce is None else nonce})
                response=connection.getresponse();return response.status,json.loads(response.read())
            finally:connection.close()
        try:
            with patch('jarvis_core.chat.gateway.probe') as model:
                self.assertEqual(call('rule-review',{},'bad')[0],403)
                status,preview=call('suggest',self.query);self.assertEqual(status,200)
                payload=self.confirmation(preview)
                status,review=call('rule-review',payload);self.assertEqual(status,200)
                status,result=call('rule-resolve',{'review_token':review['review_token'],'decision':'new','target_id':None})
                self.assertEqual(status,200);self.assertTrue(result['receipt']['committed'])
                memory=MemoryStore(self.core);row=memory.list()['facts'][0]
                _,next_preview=call('suggest',self.query)
                memory.command('correct',row['id'],'更正后的偏好',request_id=uuid.uuid4().hex)
                status,changed=call('rule-review',self.confirmation(next_preview))
                self.assertEqual(status,409);self.assertEqual(changed['error_category'],'candidate_review_changed')
                model.assert_not_called()
        finally:server.shutdown();server.server_close();thread.join(3)


if __name__=='__main__':unittest.main()
