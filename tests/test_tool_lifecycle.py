"""Admission, real LPAC canaries, evidence thresholds and reversible retirement."""
import copy
import json
import time
import uuid
from unittest.mock import patch
from test_project_tools import ProjectToolTests
from jarvis_core import policy
from jarvis_core.evolution.lifecycle import ToolLifecycle
from jarvis_core.evolution import EvolutionManager
from jarvis_core.evolution.catalog import ProjectTools
from jarvis_core.releases import RuntimeSlots


class LifecycleTests(ProjectToolTests):
    def completed(self,payload,success=True,**kw):
        return super().completed(payload,success,auto_admit=False)
    def life(self):return ToolLifecycle(self.tools)
    def state(self):return self.life().state(self.project['id'],'sum-tool')
    def observe(self,value,expected=None,useful=True):
        return self.completed(self.request('trial',input=value,expected=expected or str(sum(value)),
                                            useful=useful,benefit_note='独立加法计算，用于本项目统计。'))
    def stage(self,source=None):
        return self.completed(self.request(task_id=self.candidate(**({'source':source} if source else {}))))
    def qualify_and_promote(self,stage):
        super().qualify(stage)
        return self.completed(self.request('promote'))

    def test_new_admission_does_not_activate_until_distinct_novel_real_inputs_and_feedback(self):
        stage=self.stage();self.assertIsNone(self.tools.selected(self.project['id'],'sum-tool')['active'])
        with self.assertRaises(policy.CoreError):self.tools.submit(self.cid,self.request('run',input=[5]))
        self.assertEqual(self.tools.snapshot(self.cid)['tools'][0]['lifecycle']['phase'],'CANARY')
        failed=self.completed(self.request('promote'),False);self.assertEqual(failed['status'],'FAILED')
        self.observe([2,4]);self.observe([10],useful=False);self.observe([10],useful=False)
        a=self.life().assessment(self.project['id'],'sum-tool');self.assertEqual(a['verified_novel_inputs'],1)
        self.assertFalse(a['eligible_to_promote'])
        self.observe([10],useful=True);self.assertEqual(self.life().assessment(self.project['id'],'sum-tool')['useful_inputs'],1)
        self.observe([10],useful=False);self.assertEqual(self.life().assessment(self.project['id'],'sum-tool')['useful_inputs'],0)
        self.observe([12],useful=True)
        self.assertTrue(self.life().assessment(self.project['id'],'sum-tool')['eligible_to_promote'])
        promoted=self.completed(self.request('promote'));self.assertEqual(promoted['result']['version'],stage['result']['version'])
        actual=self.completed(self.request('run',input=[20,22],expected='42'))
        self.assertEqual(actual['result']['text'],'42');self.assertEqual(len(self.calls),1)

    def test_failure_quarantines_only_candidate_and_stable_keeps_serving(self):
        old=self.qualify_and_promote(self.stage())['result']['version']
        bad="def transform(data):\n    if data == [99]:\n        return 'broken'\n    return str(sum(data))\n"
        new=self.stage(bad)['result']['version'];stable=self.completed(self.request('run',input=[99],expected='99'))
        self.assertEqual(stable['result']['version'],old)
        failure=super().completed(self.request('trial',input=[99],expected='99',useful=True,benefit_note='独立核对本次整数结果。'),False)
        self.assertEqual(failure['status'],'FAILED');self.assertIsNone(failure['result'])
        self.assertEqual(self.state()['phase'],'REJECTED');self.assertEqual(self.tools.package(new)[1],'QUARANTINED')
        self.assertEqual(self.tools.selected(self.project['id'],'sum-tool')['active'],old)

    def test_retirement_blocks_bypass_restore_requires_fresh_canary_and_keeps_files(self):
        self.qualify_and_promote(self.stage());before=(self.source/'calc.py').read_bytes()
        retired=self.completed(self.request('retire'));self.assertEqual(retired['result']['files_deleted'],0)
        for op,kw in [('run',{'input':[5]}),('rollback',{}),('publish',{'task_id':self.candidate()})]:
            with self.assertRaises(policy.CoreError):self.tools.submit(self.cid,self.request(op,**kw))
        self.completed(self.request('restore'));self.assertIsNone(self.tools.selected(self.project['id'],'sum-tool')['active'])
        with self.assertRaises(policy.CoreError):self.tools.submit(self.cid,self.request('rollback'))
        self.assertEqual(self.completed(self.request('promote'),False)['status'],'FAILED')
        self.observe([51]);self.observe([52]);self.completed(self.request('promote'))
        self.assertEqual(self.completed(self.request('run',input=[42]))['result']['text'],'42')
        self.assertEqual((self.source/'calc.py').read_bytes(),before)

    def test_restart_pauses_without_replay_resume_and_revision_scope_guards(self):
        self.stage();self.observe([7]);count=len(self.calls)
        old=self.request('trial',input=[8],expected='8',useful=True,benefit_note='本次任务需要独立求和。')
        self.evolution.close();self.evolution=EvolutionManager(self.core,monitor=False);self.addCleanup(self.evolution.close)
        self.tools=ProjectTools(self.evolution,self.bridge)
        self.assertEqual(self.state()['phase'],'PAUSED');self.assertEqual(len(self.calls),count)
        with self.assertRaises(policy.CoreError):self.tools.submit(self.cid,old)
        with self.assertRaises(policy.CoreError):self.tools.submit(uuid.uuid4().hex,self.request('resume'))
        self.completed(self.request('resume'));self.observe([8]);self.completed(self.request('promote'))
        self.assertFalse(RuntimeSlots._compatible('0.1.74',{'optional_versions':{'evolution/evolution.db':4}}))

    def test_old_versions_retire_only_after_live_and_recovery_references_release(self):
        versions=[]
        for note in ('one','two','three'):
            version=self.qualify_and_promote(self.stage('def transform(data):\n    # '+note+'\n    return str(sum(data))\n'))['result']['version']
            versions.append(version)
        for ident in versions[1:]:
            self.assertEqual(self.completed(self.request('retire-version',version=ident),False)['status'],'FAILED')
        self.completed(self.request('retire-version',version=versions[0]))
        self.assertEqual(self.tools.package(versions[0])[1],'RETIRED')
        self.assertEqual(self.completed(self.request('run',input=[10]))['result']['text'],'10')

    def test_legacy_publication_without_review_and_evidence_cannot_bypass_gate(self):
        payload=self.request(task_id=self.candidate());payload.pop('reviewed')
        with self.assertRaises(policy.CoreError):self.tools.submit(self.cid,payload)
        payload=self.request(task_id=payload['task_id'],review_note=' '*1001+'有效审阅依据')
        with self.assertRaises(policy.CoreError):self.tools.submit(self.cid,payload)
        self.stage();self.completed(self.request('pause'))
        self.assertEqual(self.completed(self.request('trial',input=[10],expected='10',useful=True,benefit_note='独立核对该任务用途。'),False)['status'],'FAILED')
        self.completed(self.request('discard'));self.assertEqual(self.state()['phase'],'ABANDONED')
        self.stage('def transform(data):\n    # second\n    return str(sum(data))\n')

    def test_paired_quality_evidence_and_interrupted_upgrade_restore_stable_without_replay(self):
        source="def transform(data):\n    if data == [999]:\n        return '0'\n    return str(sum(data))\n"
        old=self.qualify_and_promote(self.stage(source))['result']['version']
        new=self.stage();self.observe([999]);self.observe([1001])
        assessment=self.life().assessment(self.project['id'],'sum-tool')
        self.assertEqual(assessment['paired_quality_improvements'],1)
        self.assertEqual(len(assessment['paired_observations']),2)
        promoted=self.completed(self.request('promote'));self.assertNotEqual(promoted['result']['version'],old)
        self.evolution.store.update(promoted,status='OBSERVING',tool_activation_confirmed=False)
        calls=len(self.calls)
        self.evolution.close();self.evolution=EvolutionManager(self.core,monitor=False);self.addCleanup(self.evolution.close)
        self.tools=ProjectTools(self.evolution,self.bridge)
        self.assertEqual(self.tools.selected(self.project['id'],'sum-tool')['active'],old)
        self.assertEqual(self.tools.package(new['result']['version'])[1],'QUARANTINED')
        self.assertEqual(self.state()['phase'],'REJECTED');self.assertEqual(len(self.calls),calls)
        self.assertEqual(self.completed(self.request('run',input=[1000],expected='1000'))['result']['text'],'1000')

    def test_schema3_migration_keeps_selection_legacy_and_old_receipt_is_query_only(self):
        staged=self.stage();self.qualify_and_promote(staged)
        old=copy.deepcopy(staged['request']['submission'])
        for key in ('lifecycle_revision','reviewed','review_note','minimum_verified','maximum_trials','maximum_seconds'):old.pop(key)
        staged['request']['submission']=old;self.evolution.store.update(staged)
        self.evolution.close()
        with self.evolution.store.connection() as db:
            db.execute('DROP TABLE tool_lifecycle');db.execute('PRAGMA user_version=3')
        self.evolution=EvolutionManager(self.core,monitor=False);self.addCleanup(self.evolution.close)
        self.tools=ProjectTools(self.evolution,self.bridge)
        self.assertEqual(self.state()['phase'],'LEGACY')
        self.assertEqual(self.tools.selected(self.project['id'],'sum-tool')['active'],staged['result']['version'])
        self.assertEqual(self.tools.submit(self.cid,old)['id'],staged['id'])
        with self.evolution.store.connection() as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],6)
        old['request_id']=uuid.uuid4().hex
        with self.assertRaises(policy.CoreError):self.tools.submit(self.cid,old)

    def test_trial_budget_and_stable_change_cannot_reuse_old_admission(self):
        staged=self.completed(self.request(task_id=self.candidate(),maximum_trials=2))
        self.observe([3,8]);self.observe([3,8])
        with self.assertRaises(policy.CoreError):self.tools.submit(self.cid,self.request('trial',input=[7],expected='7',useful=True,benefit_note='独立核验且用于本项目。'))
        self.assertFalse(self.life().assessment(self.project['id'],'sum-tool')['eligible_to_promote'])
        self.completed(self.request('discard'));self.qualify_and_promote(self.stage())
        self.stage('def transform(data):\n    # fresh\n    return str(sum(data))\n')
        self.completed(self.request('disable'));self.assertEqual(self.state()['phase'],'PAUSED')
        self.assertFalse(self.life().assessment(self.project['id'],'sum-tool')['stable_current'])
        self.assertEqual(self.completed(self.request('resume'),False)['status'],'FAILED')
        self.completed(self.request('discard'));self.assertIsNone(self.state()['candidate'])

    def test_corrupt_baseline_is_evidence_but_corrupt_candidate_is_quarantined(self):
        old=self.qualify_and_promote(self.stage())['result']['version']
        new=self.stage('def transform(data):\n    # candidate\n    return str(sum(data))\n')['result']['version']
        with self.evolution.store.connection() as db:db.execute("UPDATE tool_versions SET document='broken' WHERE id=?",(old,))
        trial=self.observe([52]);self.assertEqual(trial['result']['trial']['baseline']['error'],'tool_package_changed')
        self.assertEqual(self.tools.package(new)[1],'VERIFIED');self.assertEqual(self.state()['phase'],'CANARY')
        with self.evolution.store.connection() as db:db.execute("UPDATE tool_versions SET document='broken' WHERE id=?",(new,))
        failed=self.completed(self.request('trial',input=[53],expected='53',useful=True,benefit_note='独立核验本次计算结果。'),False)
        self.assertEqual(failed['status'],'FAILED');self.assertEqual(self.state()['phase'],'REJECTED')
        with self.evolution.store.connection() as db:self.assertEqual(db.execute('SELECT state FROM tool_versions WHERE id=?',(new,)).fetchone()[0],'QUARANTINED')


for name in dir(ProjectToolTests):
    if name.startswith('test_') and name not in LifecycleTests.__dict__:setattr(LifecycleTests,name,None)
del ProjectToolTests
