"""K3 receipt -> retained contract -> isolated reusable project capability."""
import copy
import json
import time
import threading
import uuid
from unittest.mock import patch
import unittest

from test_coding_workflow import CodingTests, GOOD
from jarvis_core import policy
from jarvis_core.evolution import EvolutionManager
from jarvis_core.evolution.catalog import ProjectTools
from jarvis_core.releases import RuntimeSlots
from jarvis_core.conversations import ConversationStore
from test_conversations import document


class ProjectToolTests(CodingTests):
    def setUp(self):
        super().setUp()
        doc=document();doc['project_id']=self.project['id']
        ConversationStore(self.core).put(self.cid,{'revision':0,'document':doc})
        self.evolution=EvolutionManager(self.core,monitor=False)
        self.addCleanup(self.evolution.close)
        self.tools=ProjectTools(self.evolution,self.bridge)

    def candidate(self,source=GOOD,**extra):
        self.sources=[source]
        item=self.submit(build_recipe='python-zipapp-v1',heldout_cases=[{'input':[3,8],'expected':'11'},{'input':[-4,4],'expected':'0'}],**extra)
        self.report(item)
        return item['task_id']

    def request(self,op='publish',**kw):
        base=self.tools.selected(self.project['id'],'sum-tool')
        value={'operation':op,'request_id':uuid.uuid4().hex,'tool_id':'sum-tool','generation':base['generation']}
        if op=='publish':value.update(name='求和工具',when_to_use='整数列表求和',when_not_to_use='不用于对象、字符串或财务计算')
        from jarvis_core.evolution.lifecycle import ToolLifecycle,OPERATIONS
        if op in OPERATIONS:
            value['lifecycle_revision']=ToolLifecycle(self.tools).state(self.project['id'],'sum-tool')['revision']
            if op!='trial':value.update(reviewed=True,review_note='已按独立求和要求核对本轮操作。')
        if op=='publish':value.update(minimum_verified=2,maximum_trials=10,maximum_seconds=15)
        value.update(kw);return value

    def completed(self,payload,success=True,*,auto_admit=True):
        job=self.tools.submit(self.cid,payload);deadline=time.monotonic()+50
        while time.monotonic()<deadline:
            result=self.tools.bound_job(self.cid,job['id'])
            if result['status'] not in {'QUEUED','RUNNING','OBSERVING'}:
                deadline2=time.monotonic()+2
                while self.evolution.busy and time.monotonic()<deadline2:time.sleep(.02)
                if success:self.assertEqual(result['status'],'SUCCEEDED',result.get('error'))
                if auto_admit and success and payload['operation']=='publish':
                    self.qualify(result)
                    self.completed(self.request('promote'),auto_admit=False)
                return result
            time.sleep(.04)
        self.fail('tool task timeout')

    def qualify(self,stage):
        salt=int(stage['id'][:6],16)+100
        for n in (2,3):
            self.completed(self.request('trial',input=[salt,n],expected=str(salt+n),useful=True,
                                        benefit_note='独立整数相加核算，用于本项目统计。'),auto_admit=False)

    def test_actual_publish_use_disable_restore_restart_and_idempotency(self):
        task=self.candidate();payload=self.request(task_id=task);pub=self.completed(payload)
        self.assertEqual(self.tools.submit(self.cid,payload)['id'],pub['id'])
        self.assertEqual(self.tools.snapshot(self.cid)['tools'][0]['cases'],4)
        result=self.completed(self.request('run',input=[10,20],expected='30'))
        self.assertTrue(result['result']['result_verified']);self.assertTrue(result['result']['isolation']['lpac'])
        self.assertEqual(len(self.calls),1)
        self.assertEqual((self.source/'calc.py').read_text(encoding='utf-8-sig').strip(),'def transform(data):\n    return \'wrong\'')
        self.completed(self.request('disable'));self.assertIsNone(self.tools.snapshot(self.cid)['tools'][0]['active'])
        with self.assertRaises(policy.CoreError):self.tools.submit(self.cid,self.request('run',input=[1]))
        self.completed(self.request('rollback'))
        self.evolution.close();self.evolution=EvolutionManager(self.core,monitor=False);self.addCleanup(self.evolution.close);self.tools=ProjectTools(self.evolution,self.bridge)
        self.assertEqual(self.tools.snapshot(self.cid)['tools'][0]['active'],pub['result']['version'])
        self.assertEqual(self.completed(self.request('run',input=[2]))['result']['text'],'2')

    def test_upgrade_failure_rolls_back_without_replaying_real_input(self):
        old=self.completed(self.request(task_id=self.candidate()))['result']['version']
        source="def transform(data):\n    if data == [99]:\n        return 'broken'\n    return str(sum(data))\n"
        new=self.completed(self.request(task_id=self.candidate(source)))['result']['version'];self.assertNotEqual(old,new)
        failed=self.completed(self.request('run',input=[99],expected='99'),False)
        self.assertEqual(failed['status'],'FAILED');self.assertEqual(failed['error'],'tool_result_mismatch')
        self.assertEqual(failed['rollback']['to'],old);self.assertEqual(self.tools.selected(self.project['id'],'sum-tool')['active'],old)
        self.assertIsNone(failed['result']);self.assertEqual(self.completed(self.request('run',input=[99],expected='99'))['result']['text'],'99')

    def test_unchanged_regression_with_bad_input_does_not_quarantine(self):
        version=self.completed(self.request(task_id=self.candidate()))['result']['version']
        failed=self.completed(self.request('run',input={'invalid':'shape'}),False)
        self.assertEqual(failed['status'],'FAILED');self.assertNotIn('rollback',failed)
        self.assertEqual(self.tools.selected(self.project['id'],'sum-tool')['active'],version)

    def test_source_scope_generation_and_contract_cannot_be_bypassed(self):
        task=self.candidate();self.completed(self.request(task_id=task))
        for change in [{'generation':0},{'tool_id':'../escape'},{'name':''},{'extra':'field'}]:
            with self.subTest(change=change),self.assertRaises(policy.CoreError):self.tools.submit(self.cid,self.request(task_id=task,**change))
        from jarvis_core.evolution.catalog import merge_cases
        with self.assertRaises(policy.CoreError):merge_cases([{'input':[1],'expected':'1'}],[{'input':[1],'expected':'2'}])
        with self.assertRaises(policy.CoreError):self.tools.submit(uuid.uuid4().hex,self.request(task_id=task))
        current=self.tools.selected(self.project['id'],'sum-tool')['active']
        with self.evolution.store.connection() as db:
            doc=json.loads(db.execute('SELECT document FROM tool_versions WHERE id=?',(current,)).fetchone()[0]);doc['cases'][0]['expected']='forged'
            db.execute('UPDATE tool_versions SET document=? WHERE id=?',(json.dumps(doc),current))
        failed=self.completed(self.request('run',input=[1]),False)
        self.assertEqual(failed['error'],'tool_package_changed');self.assertIsNone(self.tools.selected(self.project['id'],'sum-tool')['active'])

    def test_unconfirmed_publication_is_deactivated_on_recovery(self):
        job=self.completed(self.request(task_id=self.candidate()))
        with self.evolution.store.connection() as db:
            row=db.execute("SELECT document FROM jobs WHERE json_extract(document,'$.request.submission.operation')='promote' ORDER BY rowid DESC LIMIT 1").fetchone()
            job=json.loads(row[0])
        self.evolution.store.update(job,status='OBSERVING',tool_activation_confirmed=False)
        self.evolution.close();self.evolution=EvolutionManager(self.core,monitor=False);self.addCleanup(self.evolution.close);self.tools=ProjectTools(self.evolution,self.bridge)
        self.assertIsNone(self.tools.selected(self.project['id'],'sum-tool')['active'])
        self.assertEqual(self.evolution.store.job(job['id'])['status'],'INTERRUPTED')
        self.assertFalse(RuntimeSlots._compatible('0.1.70',{'optional_versions':{'evolution/evolution.db':3}}))
        self.assertTrue(RuntimeSlots._compatible('0.1.71',{'optional_versions':{'evolution/evolution.db':3}}))

    def test_shared_project_context_other_project_and_corrupt_json(self):
        task=self.candidate();pub=self.completed(self.request(task_id=task))
        other=uuid.uuid4().hex;doc=document();doc['project_id']=self.project['id']
        ConversationStore(self.core).put(other,{'revision':0,'document':doc})
        self.assertEqual(self.tools.snapshot(other)['tools'][0]['active'],pub['result']['version'])
        with self.assertRaises(policy.CoreError):self.tools.bound_job(other,pub['id'])
        second=self.source.parent/'second-project';second.mkdir()
        project=self.workspace.open_project({'path':str(second)});cid=uuid.uuid4().hex
        doc['project_id']=project['id'];ConversationStore(self.core).put(cid,{'revision':0,'document':doc})
        self.assertFalse(self.tools.snapshot(cid)['tools'])
        with self.assertRaises(policy.CoreError):self.tools.submit(cid,self.request(task_id=task,generation=0))
        with self.evolution.store.connection() as db:db.execute("UPDATE tool_versions SET document='broken'")
        self.assertEqual(self.tools.snapshot(self.cid)['tools'][0]['issue'],'tool_package_changed')
        failed=self.completed(self.request('run',input=[2]),False)
        self.assertEqual(failed['error'],'tool_package_changed')
        self.assertIsNone(self.tools.selected(self.project['id'],'sum-tool')['active'])

    def test_capacity_reserves_recovery_space_and_contract_is_bounded(self):
        from jarvis_core.evolution.catalog import merge_cases
        with self.assertRaises(policy.CoreError):merge_cases([], [{'input':i,'expected':str(i)} for i in range(65)])
        with self.evolution.store.connection() as db:
            db.execute('CREATE TABLE capacity_padding(value BLOB)')
            db.execute('INSERT INTO capacity_padding VALUES(zeroblob(?))',(27*1024*1024,))
        with self.assertRaises(policy.CoreError) as error:self.evolution.store.create_job({'action':'project-tool','request_id':'capacity-test'})
        self.assertEqual(error.exception.code,'evolution_quota')
        with self.evolution.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)

    def test_runtime_change_and_cancel_during_observation_disable_candidate(self):
        task=self.candidate()
        with patch.object(self.evolution,'_enqueue',side_effect=lambda value:value):frozen=self.tools.submit(self.cid,self.request(task_id=task))
        with patch('jarvis_core.evolution.catalog.runtime_binding',return_value='changed'):
            job=self.evolution._enqueue(frozen)
            while self.evolution.busy:time.sleep(.03)
        self.assertEqual(self.evolution.store.job(job['id'])['error'],'tool_runtime_changed')
        stable=self.completed(self.request(task_id=task))['result']['version']
        staged=self.completed(self.request(task_id=task),auto_admit=False);self.qualify(staged)
        entered=threading.Event();original=self.evolution.runner.run_build;calls=[]
        def observe(build,inputs,checkpoint):
            calls.append(True)
            if len(calls)==2:
                entered.set()
                while True:checkpoint();time.sleep(.02)
            return original(build,inputs,checkpoint)
        with patch.object(self.evolution.runner,'run_build',side_effect=observe):
            job=self.tools.submit(self.cid,self.request('promote'));self.assertTrue(entered.wait(25))
            self.evolution.cancel(job['id']);end=time.monotonic()+10
            while self.evolution.busy and time.monotonic()<end:time.sleep(.03)
        self.assertFalse(self.evolution.busy)
        self.assertEqual(self.evolution.store.job(job['id'])['status'],'CANCELLED')
        self.assertEqual(self.tools.selected(self.project['id'],'sum-tool')['active'],stable)

for name in dir(CodingTests):
    if name.startswith('test_') and name not in ProjectToolTests.__dict__:setattr(ProjectToolTests,name,None)
del CodingTests
if __name__=='__main__':unittest.main()
