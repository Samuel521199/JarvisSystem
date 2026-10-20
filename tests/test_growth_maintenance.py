"""Receipt integrity, bounded capacity, recovery references and directory identity."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'apps/web')]
from jarvis_core import policy
from jarvis_core.service import CoreService
from jarvis_core.evolution import EvolutionManager
from jarvis_core.evolution.maintenance import LedgerMaintenance, directory_count
from jarvis_core.evolution.store import now
from jarvis_core.conversations import ConversationStore
from jarvis_core.releases import RuntimeSlots
from jarvis_core.worker_recovery import locked
from test_conversations import document


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)/'project'; folder.mkdir()
        self.core = CoreService(Path(self.tmp.name)/'data'); self.core.initialize(folder)
        self.manager = EvolutionManager(self.core, monitor=False); self.addCleanup(self.manager.close)
        self.store = self.manager.store; self.service = LedgerMaintenance(self.manager)

    def seed(self, status='SUCCEEDED', **extra):
        ident = uuid.uuid4().hex
        value = {'id':ident, 'request':{'action':'check','request_id':'test-'+ident},
                 'status':status, 'created_at':now(), 'events':[{'phase':'DONE','detail':'e'*3000}],
                 'attempts':[], 'result':{'healthy':True}, 'error':None, **extra}
        with self.store.connection() as db:
            db.execute('INSERT INTO jobs VALUES(?,?,?,?)',(ident,value['request']['request_id'],status,policy.canonical_json(value)))
        return value

    def target(self, ident):
        row = next(x for x in self.service.preview()['jobs'] if x['id']==ident)
        return {'id':ident,'binding':row['binding']}

    def command(self, ids):
        return {'request_id':uuid.uuid4().hex,'operation':'archive-receipts',
                'targets':[self.target(i) for i in ids], 'reviewed':True,'review_note':'保留原编号与恢复材料，核对本轮容量整理。'}

    def test_preview_is_readonly_and_protects_unknown_proposed_and_unconfirmed(self):
        allowed = self.seed(); unknown=self.seed('UNKNOWN'); proposed=self.seed('PROPOSED')
        pending=self.seed(published='a'*64,activation_confirmed=False)
        before=self.store.path.read_bytes(); rows={r['id']:r for r in self.service.preview()['jobs']}
        self.assertTrue(rows[allowed['id']]['eligible'])
        for d in (unknown,proposed,pending): self.assertFalse(rows[d['id']]['eligible'])
        self.assertEqual(before,self.store.path.read_bytes())
        self.assertFalse((self.store.root/'receipt-archives').exists())

    def test_archive_original_identity_lookup_and_idempotency_survive_restart(self):
        original=self.seed(); payload=self.command([original['id']]); result=self.service.apply(payload)
        self.assertEqual(result['online_slots_released'],1)
        self.assertEqual(self.store.job(original['id']),original)
        self.assertEqual(self.store.existing_job(original['request']['request_id']),original)
        self.assertEqual(self.service.apply(payload),result)
        self.assertEqual(self.store.create_job(original['request']), (original,False))
        self.assertEqual(self.manager._enqueue(original['request']),original)
        self.manager.close(); self.manager=EvolutionManager(self.core,monitor=False);self.addCleanup(self.manager.close)
        self.assertEqual(self.manager.store.job(original['id']),original)
        changed=copy.deepcopy(payload);changed['review_note']='使用同一编号尝试替换其他内容。'
        with self.assertRaises(policy.CoreError):LedgerMaintenance(self.manager).apply(changed)
        with self.assertRaises(policy.CoreError):self.manager.store.update(original,status='QUEUED')
        self.assertEqual(self.manager.store.job(original['id'])['status'],'SUCCEEDED')

    def test_full_job_quota_does_not_block_maintenance_or_idempotent_lookup(self):
        jobs=[self.seed() for _ in range(1000)]
        with self.assertRaises(policy.CoreError):self.store.create_job({'action':'check','request_id':'new-request'})
        result=self.service.apply(self.command([j['id'] for j in jobs[:20]]))
        self.assertEqual(result['online_slots_released'],20)
        value,created=self.store.create_job({'action':'check','request_id':'new-request'})
        self.assertTrue(created);self.assertEqual(value['status'],'QUEUED')
        self.assertEqual(self.store.job(jobs[0]['id']),jobs[0])
        self.assertEqual(self.service.preview()['capacity']['online_jobs'],981)

    def test_corrupt_archive_fails_closed_and_original_request_never_reexecutes(self):
        original=self.seed();self.service.apply(self.command([original['id']]))
        archive=next((self.store.root/'receipt-archives').iterdir());archive.write_bytes(b'corrupt')
        with self.assertRaises(policy.CoreError):self.manager._enqueue(original['request'])
        self.assertFalse(self.manager.busy)
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)

    def test_stale_preview_and_batch_failure_do_not_change_online_receipts(self):
        first=self.seed();second=self.seed();payload=self.command([first['id'],second['id']])
        second['error']='changed';self.store.update(second)
        with self.assertRaises(policy.CoreError):self.service.apply(payload)
        self.assertEqual(self.service.preview()['capacity']['archived_jobs'],0)
        self.assertFalse((self.store.root/'receipt-archives').exists())
        payload=self.command([first['id'],second['id']]);save=self.service.save
        def interrupted(doc):
            if doc['id']==second['id']:raise OSError('simulated disk failure')
            return save(doc)
        with patch.object(self.service,'save',side_effect=interrupted), self.assertRaises(OSError):self.service.apply(payload)
        self.assertEqual(self.store.job(first['id']),first)
        self.assertEqual(self.service.preview()['capacity']['archived_jobs'],0)
        # Complete orphan files are verified and reused; no evidence is deleted.
        self.assertEqual(self.service.apply(payload)['online_slots_released'],2)

    def test_commit_failure_keeps_original_then_verified_orphan_can_be_reused(self):
        original=self.seed();payload=self.command([original['id']])
        with self.store.connection() as db:
            db.execute("CREATE TRIGGER reject_maintenance BEFORE INSERT ON maintenance_receipts BEGIN SELECT RAISE(ABORT,'simulated commit failure'); END")
        with self.assertRaises(policy.CoreError):self.service.apply(payload)
        self.assertEqual(self.store.job(original['id']),original)
        self.assertEqual(len(list((self.store.root/'receipt-archives').iterdir())),1)
        with self.store.connection() as db:db.execute('DROP TRIGGER reject_maintenance')
        self.assertEqual(self.service.apply(payload)['online_slots_released'],1)

    def test_conversation_lifecycle_and_parent_references_are_blocked(self):
        chat=self.seed();life=self.seed();parent=self.seed()
        child=self.seed('PROPOSED',request={'action':'check','request_id':'child-request','origin':{'previous_job':parent['id']}})
        doc=document();doc['messages'][0].update(growth_ref=chat['id'],personal_control=True)
        ConversationStore(self.core).put(uuid.uuid4().hex,{'revision':0,'document':doc})
        with self.store.connection() as db:
            db.execute('INSERT INTO tool_lifecycle VALUES(?,?,?)',('p','tool',policy.canonical_json({'phase':'ACTIVE','last_job':life['id']})))
        rows={r['id']:r for r in self.service.preview()['jobs']}
        for item in (chat,life,parent,child):self.assertFalse(rows[item['id']]['eligible'])
        with self.assertRaises(policy.CoreError):self.service.apply(self.command([chat['id']]))

    def test_busy_lane_archive_budget_and_review_checks(self):
        original=self.seed();payload=self.command([original['id']])
        self.manager.busy=True
        with self.assertRaises(policy.CoreError):self.service.apply(payload)
        self.manager.busy=False
        with locked(self.store.root/'.lane.lock'), self.assertRaises(policy.CoreError):self.service.apply(payload)
        with patch('jarvis_core.evolution.maintenance.ARCHIVE_BYTES',100),self.assertRaises(policy.CoreError):self.service.apply(payload)
        malformed=copy.deepcopy(payload);malformed['operation']=[]
        with self.assertRaises(policy.CoreError):self.service.apply(malformed)
        payload['reviewed']=False
        with self.assertRaises(policy.CoreError):self.service.apply(payload)
        self.assertEqual(self.store.job(original['id']),original)

    def seed_directory(self, pid=None, tid='old-tool'):
        pid=pid or uuid.uuid4().hex
        life={'phase':'RETIRED','revision':2,'candidate':None,'retired_version':'a'*64,'last_job':uuid.uuid4().hex}
        with self.store.connection() as db:
            db.execute('INSERT INTO project_tools VALUES(?,?,NULL,?,7)',(pid,tid,'a'*64))
            db.execute('INSERT INTO tool_lifecycle VALUES(?,?,?)',(pid,tid,policy.canonical_json(life)))
        return pid,tid,life

    def directory_command(self, pid,tid,operation):
        row=next(r for r in self.service.preview()['directories'] if r['project_id']==pid and r['tool_id']==tid)
        return {'request_id':uuid.uuid4().hex,'operation':operation,'targets':[{k:row[k] for k in ('project_id','tool_id','binding')}],
                'reviewed':True,'review_note':'核对目录退役，保留原版本和恢复身份。'}

    def test_directory_store_and_restore_release_slot_keep_identity_and_never_activate(self):
        pid,tid,life=self.seed_directory();payload=self.directory_command(pid,tid,'store-directory')
        self.assertEqual(self.service.apply(payload)['online_slots_released'],1)
        self.assertEqual(self.service.apply(payload)['online_slots_released'],1)
        with self.store.connection() as db:
            self.assertEqual(directory_count(db),0)
            row=db.execute('SELECT * FROM project_tools').fetchone();self.assertIsNone(row['active']);self.assertEqual(row['generation'],8)
        self.service.apply(self.directory_command(pid,tid,'restore-directory'))
        with self.store.connection() as db:
            self.assertEqual(directory_count(db),1)
            value=json.loads(db.execute('SELECT document FROM tool_lifecycle').fetchone()[0])
            self.assertEqual(value['phase'],'RETIRED');self.assertEqual(value['retired_version'],life['retired_version'])
            self.assertIsNone(db.execute('SELECT active FROM project_tools').fetchone()[0])
        self.assertFalse(RuntimeSlots._compatible('0.1.76',{'optional_versions':{'evolution/evolution.db':6}}))
        self.assertTrue(RuntimeSlots._compatible('0.1.77',{'optional_versions':{'evolution/evolution.db':6}}))

    def test_directory_restore_rejects_full_capacity_and_pending_project(self):
        pid,tid,_=self.seed_directory()
        pending=self.seed('UNKNOWN',request={'action':'project-tool-plan','request_id':'pending','scope':{'project_id':pid}})
        with self.assertRaises(policy.CoreError):self.service.apply(self.directory_command(pid,tid,'store-directory'))
        pending['status']='CANCELLED';self.store.update(pending)
        self.service.apply(self.directory_command(pid,tid,'store-directory'))
        for _ in range(32):self.seed_directory()
        with self.assertRaises(policy.CoreError):self.service.apply(self.directory_command(pid,tid,'restore-directory'))

    def test_archive_file_and_audit_budgets_remain_bounded(self):
        first=self.seed();second=self.seed()
        with patch('jarvis_core.evolution.maintenance.ARCHIVE_COUNT',1):
            self.service.apply(self.command([first['id']]))
            with self.assertRaises(policy.CoreError):self.service.apply(self.command([second['id']]))
        with patch('jarvis_core.evolution.maintenance.MAINTENANCE_LIMIT',1),self.assertRaises(policy.CoreError):
            self.service.apply(self.command([second['id']]))
        self.assertEqual(self.store.job(second['id']),second)

    def test_small_terminal_receipts_can_release_online_slot_without_claiming_byte_savings(self):
        value=self.seed(events=[],result=None)
        self.assertEqual(self.service.apply(self.command([value['id']]))['online_slots_released'],1)
        self.assertEqual(self.store.job(value['id']),value)


from test_evolution import EvolutionHTTPTests
class MaintenanceHTTPTests(EvolutionHTTPTests):
    def test_maintenance_auth_and_query_remain_available_when_queue_full(self):
        self.assertEqual(self.request('GET','/api/evolution/maintenance',headers={'X-Jarvis-Nonce':'bad'})[0],403)
        self.assertEqual(self.request('GET','/api/evolution/maintenance',headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('POST','/api/evolution/maintenance',{},headers={'X-Jarvis-Nonce':'bad'})[0],403)
        status,raw=self.request('GET','/api/evolution/maintenance');self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)['model_calls'],0)
        self.assertEqual(self.request('GET','/api/evolution/maintenance?path=secret')[0],404)
        self.assertEqual(self.request('POST','/api/evolution/maintenance',{'operation':'delete'})[0],400)
        invalid={'request_id':uuid.uuid4().hex,'operation':[],'targets':[], 'reviewed':True,'review_note':'核对无效请求不会触发副作用。'}
        self.assertEqual(self.request('POST','/api/evolution/maintenance',invalid)[0],400)
        self.assertEqual(self.provider.calls,[])

for name in dir(EvolutionHTTPTests):
    if name.startswith('test_') and name not in MaintenanceHTTPTests.__dict__:setattr(MaintenanceHTTPTests,name,None)
del EvolutionHTTPTests

from test_project_tools import ProjectToolTests
class MaintenanceToolTests(ProjectToolTests):
    def test_archived_verified_run_keeps_result_and_regression_for_future_candidates(self):
        self.completed(self.request(task_id=self.candidate()))
        run=self.completed(self.request('run',input=[8,8],expected='16'))
        maintenance=LedgerMaintenance(self.evolution)
        row=next(r for r in maintenance.preview()['jobs'] if r['id']==run['id'])
        self.assertTrue(row['eligible'],row['reasons'])
        maintenance.apply({'request_id':uuid.uuid4().hex,'operation':'archive-receipts',
                           'targets':[{'id':run['id'],'binding':row['binding']}],
                           'reviewed':True,'review_note':'保留核验结果与原编号，验证升级不能丢失旧案例。'})
        self.assertEqual(self.tools.bound_job(self.cid,run['id']),run)
        self.assertEqual(self.tools.snapshot(self.cid)['tools'][0]['usage']['verified_results'],1)
        source="def transform(data):\n    return 'bad' if data==[8,8] else str(sum(data))\n"
        failed=self.completed(self.request(task_id=self.candidate(source)),False,auto_admit=False)
        self.assertEqual(failed['status'],'FAILED');self.assertEqual(failed['error'],'tool_regression')
        self.assertEqual(self.completed(self.request('run',input=[8,8],expected='16'))['result']['text'],'16')

    def test_stored_identity_cannot_be_reused_and_restore_requires_fresh_canary(self):
        self.completed(self.request(task_id=self.candidate()))
        self.completed(self.request('retire'))
        maintenance=LedgerMaintenance(self.evolution)
        def apply(operation):
            row=maintenance.preview()['directories'][0]
            return maintenance.apply({'request_id':uuid.uuid4().hex,'operation':operation,
                'targets':[{k:row[k] for k in ('project_id','tool_id','binding')}],
                'reviewed':True,'review_note':'保留原身份恢复材料，收存后再以退役状态恢复。'})
        apply('store-directory')
        with self.assertRaises(policy.CoreError):self.tools.submit(self.cid,self.request('rollback'))
        from jarvis_core.evolution.tool_intent import ToolIntents
        self.assertEqual(ToolIntents(self.tools).catalog(self.cid),[])
        apply('restore-directory')
        restored=self.completed(self.request('restore'))
        self.assertIsNone(self.tools.selected(self.project['id'],'sum-tool')['active'])
        from jarvis_core.evolution.lifecycle import ToolLifecycle
        life=ToolLifecycle(self.tools).state(self.project['id'],'sum-tool');self.assertEqual(life['phase'],'CANARY')
        self.qualify(restored);self.completed(self.request('promote'))
        self.assertEqual(self.completed(self.request('run',input=[3,5],expected='8'))['result']['text'],'8')

for name in dir(ProjectToolTests):
    if name.startswith('test_') and name not in MaintenanceToolTests.__dict__:setattr(MaintenanceToolTests,name,None)
del ProjectToolTests


if __name__=='__main__': unittest.main()
