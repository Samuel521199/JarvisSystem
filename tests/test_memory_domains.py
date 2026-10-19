"""Classification, scope, provenance and actual routed context; synthetic only."""
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core.chat import ChatService
from jarvis_core.conversations import ConversationStore
from jarvis_core.memory import MemoryStore, MemoryError
from jarvis_core.memory_policy import SUBJECTS
from jarvis_core.personal_candidates import PersonalCandidates
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService


def classification(kind='personal_fact', uses=None, expires=None, label=''):
    return {'kind':kind, 'subject':SUBJECTS[kind], 'subject_label':label,
            'uses':['personal_chat'] if uses is None else uses, 'expires_at':expires}


class MemoryDomainTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name); folder=self.base/'project'; folder.mkdir()
        self.core=CoreService(self.base/'data'); self.core.initialize(folder)
        self.project=WorkspaceService(self.core).open_project({'path':str(folder)})['id']
        other=self.base/'other';other.mkdir()
        self.other=WorkspaceService(self.core).open_project({'path':str(other)})['id']
        self.store=MemoryStore(self.core)

    def put(self, content, meta=None, project=None, providers=None, title=None):
        doc={'title':title or content[:30], 'content':content, 'project_id':project, 'providers':providers or []}
        if meta is not None:doc['classification']=meta
        return self.store.put(uuid.uuid4().hex, {'revision':0, 'document':doc})

    def ctx(self, project=None, purpose=None):
        return {'enabled':True, 'project_id':project, **({'purpose':purpose} if purpose else {})}

    def test_personal_work_shared_and_unclassified_default_views(self):
        self.put('PRIVATE_HEALTH',classification())
        self.put('SHORT_ANSWERS',classification('preference',['personal_chat','work_assist']))
        self.put('PROJECT_DECISION',classification('project_fact',['work_assist']),self.project)
        self.put('LEGACY')
        private,info=self.store.context(self.ctx(),'local')
        self.assertIn('PRIVATE_HEALTH',private);self.assertNotIn('PROJECT_DECISION',private)
        work,info=self.store.context(self.ctx(self.project),'local')
        self.assertEqual(info['purpose'],'work_assist')
        self.assertNotIn('PRIVATE_HEALTH',work);self.assertIn('SHORT_ANSWERS',work)
        self.assertIn('PROJECT_DECISION',work);self.assertIn('LEGACY',work)

    def test_purpose_does_not_expand_project_or_provider_scope(self):
        self.put('ALPHA',classification('project_fact',['work_assist']),self.project,['vertex'])
        self.put('BETA',classification('project_fact',['work_assist']),self.other,['vertex'])
        self.put('LOCAL',classification('preference',['work_assist']))
        self.put('PRIVATE',classification(),providers=['vertex'])
        text,_=self.store.context(self.ctx(self.project),'vertex')
        for secret in ('BETA','LOCAL','PRIVATE'):self.assertNotIn(secret,text)
        self.assertIn('ALPHA',text)
        union=dict(self.ctx(self.project),project_ids=[self.project,self.other])
        text,_=self.store.context(union,'vertex');self.assertIn('BETA',text)
        self.assertNotIn('BETA',self.store.context(self.ctx(self.project),'vertex')[0])

    def test_subject_and_expiry_validation(self):
        for meta,project in [
            (classification('project_fact',['work_assist']),None),
            (classification('work_result',['work_assist']),None),
            (classification('third_party'),None), (classification('fiction'),None),
            (classification('temporary_state'),None),
            (classification(expires='2026-02-30T00:00:00Z'),None),
            (dict(classification(),subject='other'),None),
            (classification(label='客户'),None),
            (classification(uses=['external_output']),None),
        ]:
            with self.subTest(meta=meta),self.assertRaises(MemoryError):self.put('bad',meta,project)
        self.assertEqual(self.store.list()['facts'],[])

    def test_customer_subject_is_explicit_and_fiction_stays_out(self):
        self.put('客户喜欢红色',classification('third_party',['work_assist'],label='客户王先生'),self.project)
        self.put('虚构人物会飞',classification('fiction',[],label='NPC王先生'))
        text,_=self.store.context(self.ctx(self.project),'local')
        self.assertIn('客户王先生',text);self.assertIn('"subject":"other"',text)
        self.assertNotIn('虚构人物',text)
        self.assertEqual(len(self.store.list(project_id=self.project)['facts']),2)

    def test_expired_and_stored_only_visible_but_not_used(self):
        expired=self.put('TEMP',classification('temporary_state',expires='2000-01-01T00:00:00Z'))
        held=self.put('HOLD',classification(uses=[]))
        states={r['id']:r['usage']['state'] for r in self.store.list()['facts']}
        self.assertEqual(states[expired['id']],'expired');self.assertEqual(states[held['id']],'stored_only')
        self.assertEqual(self.store.context(self.ctx(),'local')[0],'')

    def test_expiry_rechecked_on_existing_snapshot(self):
        row=self.put('EXPIRED_LATER',classification(expires='2030-01-01T00:00:00Z'))
        facts=self.store.view_facts(self.ctx(),'local')
        from datetime import datetime,timezone
        from jarvis_core import memory_policy
        original=memory_policy.eligible
        with patch('jarvis_core.memory_policy.eligible',side_effect=lambda d,u:original(d,u,now=datetime(2031,1,1,tzinfo=timezone.utc))):
            self.assertEqual(self.store.context(self.ctx(),'local',facts=facts)[0],'')
            history=[{'role':'user','content':'hi'},{'role':'assistant','content':'EXPIRED_LATER'}]
            self.assertEqual(self.store.filter_history(history,[[],[{'id':row['id'],'revision':1}]],self.ctx(),'local',facts=facts)[0],[])

    def test_old_editor_cannot_drop_restrictions_and_chat_edit_preserves_them(self):
        row=self.put('OLD',classification(uses=[]));doc=copy.deepcopy(row['document']);del doc['classification']
        doc['content']='NEW';updated=self.store.put(row['id'],{'revision':1,'document':doc})
        self.assertEqual(updated['document']['classification']['uses'],[])
        request=uuid.uuid4().hex
        receipt=self.store.command('correct','OLD','CHAT_EDIT',request_id=request)
        self.assertTrue(self.store.command('correct','OLD','CHAT_EDIT',request_id=request)['replayed'])
        self.assertEqual(receipt['revision'],3);self.assertEqual(self.store.context(self.ctx(),'local')[0],'')
        doc['classification']=None
        with self.assertRaises(MemoryError):self.store.put(row['id'],{'revision':3,'document':doc})

    def test_restricting_purpose_invalidates_stale_history_and_snapshot(self):
        row=self.put('DERIVED_PRIVATE',classification('preference',['personal_chat','work_assist']))
        ctx=self.ctx(purpose='work_assist');facts=self.store.view_facts(ctx,'local')
        doc=copy.deepcopy(row['document']);doc['classification']['uses']=['personal_chat']
        self.store.put(row['id'],{'revision':1,'document':doc})
        self.assertEqual(self.store.context(ctx,'local',facts=facts)[0],'')
        history=[{'role':'user','content':'old'},{'role':'assistant','content':'DERIVED_PRIVATE'}]
        self.assertEqual(self.store.filter_history(history,[[],[{'id':row['id'],'revision':1}]],ctx,'local',facts=facts)[0],[])

    def test_v2_migration_preserves_every_existing_row_and_does_not_classify(self):
        self.put('OLD_DATA');deleted=self.put('ERASE');self.store.delete(deleted['id'],{'revision':1})
        tables=('facts','receipts','fact_origins','candidate_bindings')
        with closing(sqlite3.connect(self.store.path)) as db:
            before={t:db.execute('SELECT * FROM '+t).fetchall() for t in tables}
            db.execute('PRAGMA user_version=2')
            db.commit()
        self.assertEqual(self.store.list()['facts'][0]['usage']['state'],'legacy')
        with self.store.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3)
            self.assertEqual(before,{t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in tables})

    def candidate(self):
        cid=uuid.uuid4().hex
        body='我平时喜欢无糖茶。今天有私人的健康问题。项目甲的预算是五十万元。'
        doc={'title':'mixed','project_id':None,'context_note':'','messages':[
            {'role':'user','content':body,'meta':'','short_meta':'','attachments_omitted':False,'incomplete':False}]}
        ConversationStore(self.core).put(cid,{'revision':0,'document':doc})
        service=PersonalCandidates(self.core);suggest=service.suggest({'source':{'conversation_id':cid,'message_index':0},'project_id':None})
        payload={k:suggest[k] for k in ('source','project_id','source_digest','preview_token')}
        payload.update(candidate=suggest['candidates'][0],scope='global')
        receipt=service.confirm(payload)['receipt']
        return cid,payload,receipt

    def test_mixed_message_saves_only_confirmed_claim_not_whole_source(self):
        cid,payload,receipt=self.candidate()
        row=self.store.list()['facts'][0];doc=row['document']
        doc['classification']=classification('preference',['personal_chat','work_assist'])
        self.store.put(row['id'],{'revision':row['revision'],'document':doc})
        text,_=self.store.context(self.ctx(purpose='work_assist'),'local')
        self.assertIn('无糖茶',text);self.assertNotIn('健康问题',text);self.assertNotIn('五十万元',text)
        self.assertEqual(self.store.list()['facts'][0]['provenance']['state'],'current')
        archive=ConversationStore(self.core).get(cid);archive['document']['messages'][0]['content']='来源已经修改'
        ConversationStore(self.core).put(cid,{'revision':archive['revision'],'document':archive['document']})
        self.assertEqual(self.store.context(self.ctx(purpose='work_assist'),'local')[0],'')

    def test_forget_and_delayed_candidate_cannot_revive_classified_fact(self):
        _,payload,receipt=self.candidate();row=self.store.list()['facts'][0]
        row['document']['classification']=classification()
        self.store.put(row['id'],{'revision':1,'document':row['document']})
        self.store.delete(row['id'],{'revision':2})
        payload['candidate']['title']='另一个标题'
        with self.assertRaises(MemoryError):PersonalCandidates(self.core).confirm(payload)
        self.assertEqual(self.store.list()['facts'],[])

    def test_route_fallback_rebuilds_actual_context_and_derived_history(self):
        private=self.put('PRIVATE_REASON',classification(),providers=['vertex','openai'])
        # This test concerns routing of applicable expression preferences, not
        # filling a prompt with every unrelated fact. Keep all exclusion checks.
        self.put('ROUTE_A',classification('preference',['work_assist']),providers=['vertex'],title='回复风格')
        self.put('SHARED_STYLE',classification('preference',['work_assist']),providers=['vertex','openai'],title='回复风格')
        config=json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        config.update(default_provider='vertex',automatic_fallback=True,fallback_order=['openai'])
        path=self.base/'providers.json';path.write_text(json.dumps(config),encoding='utf-8')
        calls=[]
        def probe(config,provider,message,*args,**kwargs):
            calls.append((message,kwargs['history']))
            return {'status':'FAILED','error_category':'quota_exhausted','outcome_uncertain':False} if provider=='vertex' else {'status':'SUCCEEDED','text':'ok','outcome_uncertain':False}
        with patch('jarvis_core.chat.gateway.probe',side_effect=probe):
            result=ChatService(self.core,path).reply('请协助工作',memory_context=self.ctx(purpose='work_assist'),
                history=[{'role':'user','content':'过去的话题'},{'role':'assistant','content':'PRIVATE_REASON'}],
                history_memory=[[],[{'id':private['id'],'revision':1}]])
        self.assertEqual(result['status'],'SUCCEEDED');self.assertEqual(len(calls),2)
        for message,history in calls:self.assertNotIn('PRIVATE_REASON',message);self.assertEqual(history,[])
        self.assertIn('ROUTE_A',calls[0][0]);self.assertNotIn('ROUTE_A',calls[1][0]);self.assertIn('SHARED_STYLE',calls[1][0])
        self.assertEqual(result['history_info']['memory_view']['purpose'],'work_assist')

    def test_unimplemented_recipient_and_npc_purposes_rejected_before_model(self):
        for purpose in ('external_output','npc','anything'):
            with patch('jarvis_core.chat.gateway.probe') as model:
                result=ChatService(self.core).reply('写给客户',memory_context=self.ctx(purpose=purpose))
            self.assertEqual(result['status'],'FAILED');model.assert_not_called()


if __name__=='__main__':unittest.main()
