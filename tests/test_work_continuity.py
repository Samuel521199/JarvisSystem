"""Real ledger-backed continuity; observations cannot authorize execution."""
import copy
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'runtime/node-host'),str(ROOT/'apps/web')]
import test_growth_demand as fixtures
from test_growth_demand import uid
from jarvis_core.chat import ChatService
from jarvis_core.continuity import ContinuityStore,validate_history_references
from jarvis_core.work_state import WorkState,validate_links
from jarvis_core.memory import MemoryError
from jarvis_core.conversations import validate_document
from jarvis_core.workspace import WorkspaceService


class WorkContinuityTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.GrowthDemandTests();self.addCleanup(self.fx.doCleanups);self.fx.setUp()
        self.core=self.fx.core;self.store=ContinuityStore(self.core);self.cid=self.fx.cid
        self.task={'kind':'task','id':self.fx.source_task['task_id'],'conversation_id':self.cid}
        message='保存接续：报告=报告任务还未完成｜核对交付结果'
        archive=self.fx.conversations.get(self.cid);doc=archive['document'];index=len(doc['messages'])
        doc['messages'].append({'role':'user','content':message,'meta':'','short_meta':'','attachments_omitted':False,'incomplete':False,'personal_control':True})
        self.fx.conversations.put(self.cid,{'revision':archive['revision'],'document':doc})
        self.receipt=self.store.change('save',request_id=uid(),target='报告',progress='报告任务还未完成',next_step='核对交付结果',
            source={'conversation_id':self.cid,'message_index':index},message=message)
        self.ctx={'enabled':True,'ids':[self.receipt['id']]}

    def change(self,action,**kwargs):return self.store.change(action,request_id=uid(),target=self.receipt['id'],**kwargs)
    def link(self,*refs):return self.change('link_work',work_refs=list(refs))
    def snapshot(self,provider='local'):return self.store.snapshot(self.ctx,None,provider)[0]

    def test_link_does_not_execute_and_snapshot_verifies_real_artifact(self):
        self.link(self.task);self.assertEqual(self.fx.provider.calls,[])
        row=self.snapshot()[0];item=row['work']['items'][0]
        self.assertEqual(item['state'],'completed');self.assertTrue(item['artifact_verified'])
        self.assertIn('还未完成',row['document']['progress'])
        text,report=self.store.context([row],max_bytes=4096)
        self.assertIn('linked_work',text);self.assertNotIn('中文.md',text);self.assertNotIn('total_bytes',text)
        self.assertEqual(report['references'][0]['work_digest'],row['work']['digest'])
        before=row['work']['digest'];self.assertEqual(self.snapshot()[0]['work']['digest'],before)
        view=self.store.work_view(self.receipt['id']);self.assertIn(self.task,view['choices'])
        self.assertEqual(len(self.core.status()['tasks']),1)

    def test_pending_cancelled_change_invalidates_derived_history(self):
        self.fx.tasks.queue.set_paused(True)
        task=self.fx.bridge.tasks.submit(self.cid,{'request_id':'web-'+uid(),'prompt':'列出样例并保存报告','model':'auto'})
        ref={**self.task,'id':task['task_id']};self.link(ref)
        before=self.snapshot();self.assertEqual(before[0]['work']['items'][0]['state'],'pending')
        _,report=self.store.context(before,max_bytes=4096)
        history=[{'role':'user','content':'继续'},{'role':'assistant','content':'OLD_PENDING_STATE'}]
        references=[[],report['references']]
        self.assertEqual(len(self.store.filter_history(history,references,before)[0]),2)
        self.fx.bridge.tasks.cancel(self.cid,task['task_id'],{})
        after=self.snapshot();self.assertEqual(after[0]['work']['items'][0]['state'],'cancelled')
        self.assertEqual(after[0]['revision'],before[0]['revision'])
        self.assertEqual(self.store.filter_history(history,references,after)[0],[])
        self.assertEqual(self.fx.tasks.queue.snapshot()['paused'],True)

    def test_all_terminal_labels_and_unknown_never_completed(self):
        self.link(self.task)
        mapping={'FAILED':'failed','UNKNOWN':'unknown','CANCELLED':'cancelled','RUNNING':'running'}
        for raw,state in mapping.items():
            record=self.core.ledger.record(task_id=self.task['id']);record['task']['status']=raw
            with self.core.ledger.transaction() as db:self.core.ledger._save(db,record)
            item=self.snapshot()[0]['work']['items'][0]
            self.assertEqual(item['state'],state);self.assertFalse(item['artifact_verified'])

    def test_growth_proposal_to_completed_and_tampered_result(self):
        job=self.fx.preview();ref={'kind':'growth','id':job['id'],'conversation_id':self.cid};self.link(ref)
        before=self.snapshot();self.assertEqual(before[0]['work']['items'][0]['state'],'pending')
        done=self.fx.wait(self.fx.bridge.start(self.cid,job['id'],{}));self.assertEqual(done['status'],'SUCCEEDED')
        after=self.snapshot();self.assertEqual(after[0]['work']['items'][0]['state'],'completed')
        self.assertNotEqual(before[0]['work']['digest'],after[0]['work']['digest'])
        done['result']['text']='tampered';self.fx.manager.store.update(done)
        self.assertEqual(self.snapshot()[0]['work']['items'][0]['state'],'unavailable')

    def test_artifact_damage_invalidates_old_completed_context(self):
        self.link(self.task);before=self.snapshot();_,info=self.store.context(before,max_bytes=4096)
        artifact=self.core.ledger.record(task_id=self.task['id'])['artifact']
        (self.core.ledger.artifact_dir/artifact['path']).write_bytes(b'changed')
        after=self.snapshot();self.assertEqual(after[0]['work']['items'][0]['state'],'unavailable')
        self.assertEqual(self.store.filter_history([{'role':'user','content':'old'}],[info['references']],after)[0],[])

    def test_scope_binding_missing_source_and_unlink(self):
        forged={**self.task,'conversation_id':uid()}
        with self.assertRaises(MemoryError):self.link(forged)
        self.link(self.task)
        project=WorkspaceService(self.core).open_project({'path':str(self.fx.root/'source')})['id']
        self.assertFalse(self.store.snapshot(self.ctx,project,'local')[0])
        archive=self.fx.conversations.get(self.cid);doc=archive['document'];doc['project_id']=project
        self.fx.conversations.put(self.cid,{'revision':archive['revision'],'document':doc})
        self.assertFalse(self.snapshot())
        self.link();self.assertEqual(self.store.list()['records'][0]['document']['work_refs'],[])

    def test_provider_denial_before_work_read_and_unselected_is_lazy(self):
        self.link(self.task)
        with patch.object(WorkState,'observe',side_effect=AssertionError('must not read')):
            self.assertEqual(self.store.snapshot(self.ctx,None,'vertex')[0],[])
            self.assertEqual(self.store.snapshot({'enabled':False,'ids':[]},None,'local')[0],[])
            self.assertEqual(len(self.store.list()['records']),1)
        self.change('permissions',providers=['vertex'])
        self.assertEqual(self.snapshot('vertex')[0]['work']['items'][0]['state'],'completed')

    def test_request_local_scope_cache_does_not_create_growth_store(self):
        reader=WorkState(self.core)
        with patch.object(reader.archives,'get',wraps=reader.archives.get) as get:
            reader.observe([self.task],None);reader.observe([self.task],None)
            self.assertEqual(get.call_count,1)
        other=self.fx.root/'empty';other.mkdir()
        from jarvis_core.service import CoreService
        core=CoreService(other/'data');core.initialize(self.fx.root/'source')
        from jarvis_core.conversations import ConversationStore
        archive=self.fx.conversations.get(self.cid)['document'];ConversationStore(core).put(self.cid,{'revision':0,'document':archive})
        self.assertEqual(WorkState(core).observe([{'kind':'growth','id':uid(),'conversation_id':self.cid}],None)['items'][0]['state'],'unavailable')
        self.assertFalse((core.data_dir/'evolution').exists())

    def test_idempotence_stale_revision_and_link_limits(self):
        request=uid();args={'request_id':request,'target':self.receipt['id'],'revision':1,'work_refs':[self.task]}
        self.store.change('link_work',**args);self.assertTrue(self.store.change('link_work',**args)['replayed'])
        with self.assertRaises(MemoryError):self.store.change('link_work',**{**args,'work_refs':[]})
        with self.assertRaises(MemoryError):self.change('link_work',revision=1,work_refs=[])
        for invalid in ([self.task]*2,[{**self.task,'kind':'shell'}],[{**self.task,'command':'run'}],[None],None,[self.task]*4):
            with self.assertRaises(MemoryError):validate_links(invalid)

    def test_reference_validation_and_archive_roundtrip(self):
        self.link(self.task);_,info=self.store.context(self.snapshot(),max_bytes=4096)
        doc=self.fx.conversations.get(self.cid)['document'];doc['messages'][0]['continuity_refs']=info['references'];validate_document(doc)
        for value in ('bad',None,123):
            bad=copy.deepcopy(info['references']);bad[0]['work_digest']=value
            with self.assertRaises(MemoryError):validate_history_references([bad],[{}])
        validate_history_references([[{'id':self.receipt['id'],'revision':1}]],[{}])

    def test_new_chat_uses_fresh_work_and_revokes_old_history(self):
        self.link(self.task);self.change('permissions',providers=['vertex']);chat=ChatService(self.core);calls=[]
        def probe(config,provider,message,*args,**kwargs):
            calls.append({'message':message,'history':kwargs['history']})
            return {'status':'SUCCEEDED','text':'已核对执行状态','provider':provider,'model':config['providers'][provider]['model']}
        kwargs={'provider':'vertex','personal_context':{'temporary':False},'memory_context':{'enabled':True,'project_id':None},'continuity_context':self.ctx}
        with patch('jarvis_core.chat.gateway.probe',side_effect=probe):
            first=chat.reply('继续核对',**kwargs);self.assertEqual(first['status'],'SUCCEEDED',first)
            self.assertIn('completed',calls[-1]['message'])
            history=[{'role':'user','content':'继续核对'},{'role':'assistant','content':'OLD_COMPLETED_STATE'}]
            refs=[[],first['history_info']['continuity']['references']]
            self.link()
            second=chat.reply('现在呢',history=history,history_continuity=refs,**kwargs)
            self.assertEqual(second['status'],'SUCCEEDED',second);self.assertEqual(calls[-1]['history'],[])
            self.assertNotIn('linked_work":',calls[-1]['message'])

    def test_real_http_scope_nonce_and_strict_write(self):
        import server as web
        server=web.create_server(core=self.core,chat=ChatService(self.core),port=0)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        try:
            host='127.0.0.1:'+str(server.server_port);url='/api/continuity/'+self.receipt['id']
            def request(method,path,payload=None,nonce=True):
                conn=http.client.HTTPConnection(host,timeout=5)
                headers={'Origin':'http://'+host,'Content-Type':'application/json'}
                if nonce:headers['X-Jarvis-Nonce']=server.nonce
                conn.request(method,path,json.dumps(payload) if payload is not None else None,headers);response=conn.getresponse();data=json.loads(response.read());conn.close();return response.status,data
            self.assertEqual(request('GET',url+'/work',nonce=False)[0],403)
            self.assertEqual(request('GET',url+'/work')[0],200)
            payload={'action':'link_work','revision':1,'request_id':uid(),'project_id':None,'work_refs':[self.task]}
            self.assertEqual(request('POST',url,payload)[0],200)
            self.assertEqual(request('GET',url+'/work')[1]['observed']['items'][0]['state'],'completed')
            self.assertEqual(request('POST',url,{**payload,'shell':'bad'})[0],400)
        finally:server.shutdown();server.server_close();thread.join(2)


if __name__=='__main__':unittest.main()
