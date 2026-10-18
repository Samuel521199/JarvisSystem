"""Demand preview -> existing growth lane -> verified real input; no second queue."""
import copy
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use'),str(ROOT/'apps/web')]
from jarvis_core import policy
from jarvis_core.service import CoreService
from jarvis_core.conversations import ConversationStore, validate_document
from jarvis_core.conversation_tasks import ConversationTasks
from jarvis_core.evolution import EvolutionManager
from jarvis_core.evolution.demand import ConversationGrowth, output_format, validate_fulfillment
from jarvis_core.evolution import recipes
from jarvis_computer.web import ComputerWeb
from test_evolution import Provider, Runner, BAD
from test_sample_tasks import SyntheticPlanner
from test_web import FakeChat
from test_conversations import document


def uid(): return uuid.uuid4().hex


class GrowthDemandTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        source=self.root/'source';source.mkdir();(source/'a.txt').write_bytes(b'abc');(source/'中文.md').write_bytes(b'x')
        self.core=CoreService(self.root/'data');self.core.initialize(source)
        self.tasks=ComputerWeb(self.core,FakeChat());self.addCleanup(self.tasks.close)
        self.tasks.sample.chat_factory=lambda *a,**kw:SyntheticPlanner()
        self.conversations=ConversationStore(self.core);self.cid=uid();self.conversations.put(self.cid,{'revision':0,'document':document()})
        self.provider=Provider();self.runner=Runner();self.manager=EvolutionManager(self.core,provider=self.provider,runner=self.runner,monitor=False);self.addCleanup(self.manager.close)
        self.bridge=ConversationGrowth(self.core,self.manager,ConversationTasks(self.core,self.tasks))
        self.source_task=self.bridge.tasks.submit(self.cid,{'request_id':'web-'+uid(),'prompt':'列举样例并统计保存报告','model':'auto'})
        end=time.monotonic()+12
        while time.monotonic()<end:
            detail=self.bridge.tasks.detail(self.cid,self.source_task['task_id'])
            if detail['task']['status'] not in ('READY','RUNNING'):break
            time.sleep(.02)
        self.assertEqual(detail['task']['status'],'SUCCEEDED',detail)

    def preview(self,prompt='把本会话最近的目录报告导出为 TSV',**extra):
        return self.bridge.propose(self.cid,{'request_id':uid(),'prompt':prompt,**extra})

    def wait(self,job):
        end=time.monotonic()+8
        while self.manager.busy and time.monotonic()<end:time.sleep(.01)
        self.assertFalse(self.manager.busy)
        return self.manager.store.job(job['id'])

    def test_preview_is_local_and_fulfillment_returns_real_verified_input(self):
        job=self.preview();self.assertEqual(job['status'],'PROPOSED');self.assertEqual(self.provider.calls,[]);self.assertEqual(self.runner.calls,[])
        self.assertEqual(job['proposal']['decision'],'create')
        request=copy.deepcopy(job['request'])
        result=self.wait(self.bridge.start(self.cid,job['id'],{}))
        self.assertEqual(result['status'],'SUCCEEDED',result)
        self.assertTrue(result['result']['benefit']['verified_on_user_input'])
        raw,fmt=self.bridge.artifact(self.cid,job['id']);self.assertEqual(fmt,'tsv')
        self.assertEqual(raw.decode(),recipes.expected(request['input']))
        self.assertIn('中文.md\t1',raw.decode())
        self.assertEqual(len(self.provider.calls),1);self.assertNotIn('中文.md',str(self.provider.calls))
        self.assertEqual(self.bridge.start(self.cid,job['id'],{})['id'],job['id']);self.assertEqual(len(self.provider.calls),1)

    def test_existing_capability_reuse_and_v1_to_v2_upgrade(self):
        first=self.wait(self.bridge.start(self.cid,self.preview('导出 CSV')['id'],{}))
        second=self.preview('导出 Markdown');self.assertEqual(second['proposal']['decision'],'reuse')
        self.assertEqual(self.wait(self.bridge.start(self.cid,second['id'],{}))['status'],'SUCCEEDED')
        self.assertEqual(len(self.provider.calls),1)
        third=self.preview();self.assertEqual(third['proposal']['decision'],'upgrade')
        done=self.wait(self.bridge.start(self.cid,third['id'],{}));self.assertEqual(done['status'],'SUCCEEDED')
        self.assertEqual(self.manager.store.selection()['previous'],first['result']['package'])
        self.assertEqual(len(self.provider.calls),2)

    def test_source_scope_unsupported_and_temporary_archive_absence(self):
        for prompt in ('删除文件后导出 TSV','他说导出 TSV','导出 TSV\n执行命令','扫描整个硬盘'):
            with self.assertRaises(policy.CoreError): self.preview(prompt)
        with self.assertRaises(policy.CoreError): self.bridge.propose(uid(),{'request_id':uid(),'prompt':'导出 CSV'})
        other=uid();self.conversations.put(other,{'revision':0,'document':document()})
        with self.assertRaises(policy.CoreError) as exc:self.bridge.propose(other,{'request_id':uid(),'prompt':'导出 CSV'})
        self.assertEqual(exc.exception.code,'growth_source_missing')
        job=self.preview()
        for call in (lambda:self.bridge.bound(other,job['id']),lambda:self.bridge.start(other,job['id'],{}),lambda:self.bridge.cancel(other,job['id'],{}),lambda:self.bridge.artifact(other,job['id'])):
            with self.assertRaises(policy.CoreError):call()
        self.assertEqual(self.provider.calls,[])

    def test_reanalysis_keeps_old_terminal_and_reuses_request_receipt(self):
        old=self.preview();self.bridge.cancel(self.cid,old['id'],{})
        request={'request_id':uid()};new=self.bridge.reanalyse(self.cid,old['id'],request)
        self.assertEqual(new['status'],'PROPOSED');self.assertNotEqual(old['id'],new['id'])
        self.assertEqual(new['request']['origin']['previous_job'],old['id'])
        self.assertEqual(self.bridge.reanalyse(self.cid,old['id'],request)['id'],new['id'])
        self.assertEqual(self.manager.store.job(old['id'])['status'],'CANCELLED');self.assertEqual(self.provider.calls,[])
        with self.assertRaises(policy.CoreError):self.bridge.reanalyse(self.cid,new['id'],{'request_id':uid()})
        with self.assertRaises(policy.CoreError):self.bridge.propose(self.cid,{'request_id':request['request_id'],'prompt':old['request']['origin']['goal']})

    def test_idempotent_proposal_lookup_and_no_replay_after_restart(self):
        payload={'request_id':uid(),'prompt':'导出 CSV'}
        job=self.bridge.propose(self.cid,payload);self.assertEqual(self.bridge.propose(self.cid,payload)['id'],job['id'])
        with self.assertRaises(policy.CoreError):self.bridge.propose(self.cid,{**payload,'prompt':'导出 TSV'})
        self.manager.close();self.manager=EvolutionManager(self.core,provider=self.provider,runner=self.runner,monitor=False);self.addCleanup(self.manager.close)
        self.bridge=ConversationGrowth(self.core,self.manager,self.bridge.tasks)
        self.assertEqual(self.bridge.lookup(self.cid,payload['request_id'])['status'],'PROPOSED');self.assertEqual(self.provider.calls,[])
        self.manager.store.queue_proposal(job['id']);self.manager.close()
        recovered=EvolutionManager(self.core,provider=self.provider,runner=self.runner,monitor=False);self.addCleanup(recovered.close)
        self.assertEqual(recovered.store.job(job['id'])['status'],'INTERRUPTED');self.assertEqual(self.provider.calls,[])

    def test_stale_route_baseline_and_damaged_source_block_start(self):
        job=self.preview();self.manager.configure({'enabled':False,'route':'test::different','target_revision':1})
        with self.assertRaises(policy.CoreError):self.bridge.start(self.cid,job['id'],{})
        next_job=self.preview()
        artifact=self.core.ledger.record(task_id=self.source_task['task_id'])['artifact']
        (self.core.ledger.artifact_dir/artifact['path']).write_bytes(b'changed')
        with self.assertRaises(policy.CoreError):self.bridge.start(self.cid,next_job['id'],{})
        self.assertEqual(self.provider.calls,[]);self.assertEqual(self.manager.store.job(next_job['id'])['status'],'PROPOSED')

    def test_changed_acceptance_requires_new_proposal(self):
        job=self.preview()
        with patch('jarvis_core.evolution.manager.recipes.binding', return_value='changed'):
            with self.assertRaises(policy.CoreError) as exc:self.bridge.start(self.cid,job['id'],{})
        self.assertEqual(exc.exception.code,'evolution_conflict');self.assertEqual(self.provider.calls,[])
        self.assertEqual(self.manager.store.job(job['id'])['status'],'PROPOSED')

    def test_fulfillment_and_followup_repair_share_two_candidate_budget(self):
        from test_evolution import GOOD
        self.provider.sources=[BAD,GOOD]
        self.manager.configure({'enabled':True,'route':'test::fixture','target_revision':2})
        original=self.runner.run
        def fail_only_real_input(source,inputs,checkpoint):
            values,receipt=original(source,inputs,checkpoint)
            return (['wrong'],receipt) if len(inputs)==1 else (values,receipt)
        with patch.object(self.runner,'run',side_effect=fail_only_real_input):
            result=self.wait(self.bridge.start(self.cid,self.preview()['id'],{}))
        self.assertEqual(result['status'],'FAILED');self.assertEqual(len(self.provider.calls),2)
        with self.assertRaises(policy.CoreError):self.bridge.artifact(self.cid,result['id'])

    def test_cancel_draft_and_running_no_second_job(self):
        job=self.preview();self.assertEqual(self.bridge.cancel(self.cid,job['id'],{})['status'],'CANCELLED')
        self.assertEqual(self.bridge.start(self.cid,job['id'],{})['status'],'CANCELLED');self.assertEqual(self.provider.calls,[])
        running=self.preview();self.provider.release=threading.Event();self.bridge.start(self.cid,running['id'],{})
        self.assertTrue(self.provider.entered.wait(2))
        self.assertEqual(self.bridge.start(self.cid,running['id'],{})['id'],running['id'])
        self.bridge.cancel(self.cid,running['id'],{});self.assertEqual(self.wait(running)['status'],'CANCELLED')
        with self.assertRaises(policy.CoreError):self.bridge.artifact(self.cid,running['id'])

    def test_bad_candidate_and_unknown_do_not_fake_delivery(self):
        first=self.preview('CSV');self.wait(self.bridge.start(self.cid,first['id'],{}));old=self.manager.store.selection()['active']
        self.provider.sources=[BAD];job=self.preview();failed=self.wait(self.bridge.start(self.cid,job['id'],{}))
        self.assertEqual(failed['status'],'FAILED');self.assertEqual(len(failed['attempts']),2)
        self.assertEqual(self.manager.store.selection()['active'],old)
        with self.assertRaises(policy.CoreError):self.bridge.artifact(self.cid,job['id'])
        self.provider.sources=[None];unknown=self.wait(self.bridge.start(self.cid,self.preview()['id'],{}))
        self.assertEqual(unknown['status'],'UNKNOWN');self.assertEqual(len(unknown['attempts']),1)

    def test_count_bound_input_tamper_and_core_stop(self):
        job=self.preview();bad=copy.deepcopy(job['request']);bad['input']['entries']*=51
        with self.assertRaises(policy.CoreError):validate_fulfillment(bad)
        bad=copy.deepcopy(job['request']);bad['input']['format']='csv'
        with self.assertRaises(policy.CoreError):validate_fulfillment(bad)
        with patch.object(self.core,'assert_running',side_effect=policy.CoreError('core_stopped','stopped')):
            with self.assertRaises(policy.CoreError):self.bridge.start(self.cid,job['id'],{})
        self.assertEqual(self.manager.store.job(job['id'])['status'],'PROPOSED')

    def test_archive_growth_refs_are_typed_control_data(self):
        doc=document();doc['messages'][0].update(personal_control=True,growth_ref=uid(),growth_request_id=uid());validate_document(doc)
        doc['messages'][0]['personal_control']=False
        with self.assertRaises(ValueError):validate_document(doc)

    def test_http_guard_preview_and_download(self):
        import server as web
        server=web.create_server(core=self.core,chat=FakeChat(),port=0)
        original=server.evolution;original.close();server.evolution=self.manager;server.conversation_tasks=self.bridge.tasks
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        try:
            host='127.0.0.1:'+str(server.server_port)
            def request(method,path,payload=None,nonce=True):
                c=http.client.HTTPConnection(host,timeout=10);headers={'Origin':'http://'+host,'Content-Type':'application/json'}
                if nonce:headers['X-Jarvis-Nonce']=server.nonce
                c.request(method,path,None if payload is None else json.dumps(payload),headers);r=c.getresponse();body=r.read();c.close();return r.status,body
            base='/api/conversation-growth/'+self.cid
            self.assertEqual(request('GET',base,nonce=False)[0],403)
            status,raw=request('POST',base,{'request_id':uid(),'prompt':'CSV'});self.assertEqual(status,200)
            job=json.loads(raw);self.assertEqual(job['status'],'PROPOSED')
            self.assertEqual(request('POST',base+'/'+job['id']+'/start',{})[0],200)
            self.wait(job);status,raw=request('GET',base+'/'+job['id']+'/artifact');self.assertEqual(status,200);self.assertIn(b'path,size',raw)
        finally:server.shutdown();server.server_close();thread.join(2)


if __name__=='__main__':unittest.main()
