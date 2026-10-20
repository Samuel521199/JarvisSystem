"""Policy/receipt tests plus actual K3 package and LPAC closed-loop execution."""
import copy
import json
import time
import uuid
from unittest.mock import patch
import unittest
from test_project_tools import ProjectToolTests
from jarvis_core import policy
from jarvis_core.evolution.growth_cycle import GrowthCycles, accounting
from jarvis_core.evolution.growth_domains import expected, specification

GOOD = "def transform(data):\n    out = []\n    for item in data:\n        value = item.strip()\n        if value and value not in out:\n            out.append(value)\n    return '\\n'.join(out)\n"


class GrowthCycleTests(ProjectToolTests):
    def setUp(self):
        super().setUp()
        self.cycles = GrowthCycles(self.evolution, self.bridge)
        self.evolution.growth = self.cycles
        self.sources = [GOOD]

    def grant(self, **changes):
        p = self.cycles.snapshot(self.cid)['policy']
        fields = {'revision','enabled','domains','model','expires_at','maximum_cycles','window_seconds',
                  'maximum_seconds','maximum_cycle_seconds','maximum_model_calls','minimum_calls_saved','maximum_memory_bytes'}
        return self.cycles.configure(self.cid, {**{k:p[k] for k in fields}, 'enabled': True,
            'model': 'vertex::gemini-3.8-flash', 'expires_at': time.time()+3600,
            'reviewed': True, 'review_note': '独立核对清单契约、观察窗口及调用预算。', **changes})

    def launch(self, **changes):
        p = self.cycles.snapshot(self.cid)['policy']
        return self.cycles.start(self.cid, {'request_id': uuid.uuid4().hex, 'goal':'每天帮我清理并去重购物和旅行清单。',
                'domain':'clean-lines','policy_revision':p['revision'], **changes})

    def drive(self, ident, until='COMPLETE', *, timeout=100):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            self.cycles.tick()
            c=self.cycles.stored(self.cid, ident)
            if c['status']==until:return c
            if c['status'] in {'PAUSED','INTERRUPTED','CANCELLED'}:return c
            # Accelerated clock ONLY in deterministic regression; live probes use real windows.
            if not c['pending'] and c['status'] in {'CANARY','OBSERVING'}:
                field='canary_epoch' if c['status']=='CANARY' else 'observation_epoch'
                c[field]=time.time()-35;self.cycles.save(c)
            time.sleep(.04)
        self.fail('cycle timeout: '+json.dumps(c,ensure_ascii=False))

    @staticmethod
    def normal_baseline(manager,job):
        return {'text':expected('clean-lines',job['request']['input']),
                'receipt':{'status':'SUCCEEDED','usage':{'input_tokens':100,'output_tokens':20},
                           'billing':{'amount':0.01,'currency':'USD'},'elapsed_seconds':1}}

    def test_actual_code_build_canary_admission_use_and_idempotence(self):
        self.grant();c=self.launch()
        with patch('jarvis_core.evolution.growth_cycle.baseline',side_effect=self.normal_baseline):
            result=self.drive(c['id'])
        self.assertEqual(result['status'],'COMPLETE',result.get('stop_reason'))
        self.assertEqual(result['assessment']['calls_saved'],5)
        self.assertTrue(all(x['lpac'] for x in [r['isolation'] for r in result['uses']]))
        self.assertEqual(len(self.calls),1)
        self.assertNotIn('samples',self.calls[0]);self.assertNotIn('旅行',json.dumps(self.calls[0].get('cases')))
        self.assertEqual(self.cycles.start(self.cid,c['submission'])['id'],c['id'])
        self.assertFalse(list(self.source.glob('jarvis_growth_*.py')))
        self.assertEqual(result['feedback']['useful'],None)
        self.assertTrue(result['assessment']['verified'])
        with self.assertRaises(policy.CoreError) as cm:self.launch()
        self.assertEqual(cm.exception.code,'growth_reuse_available')

    def test_domain_ambiguity_wrong_unit_and_scope_fail_before_model(self):
        self.grant()
        for change in ({'domain':'arbitrary-business'}, {'policy_revision':0}):
            with self.assertRaises(policy.CoreError):self.launch(**change)
        for domain, value in [('byte-total',[{'size':2,'unit':'KB'}]),('group-counts',[{'group':'x','count':True}]),('clean-lines',[3])]:
            with self.assertRaises(policy.CoreError):expected(domain,value)
        self.assertEqual(len(self.calls),0)

    def test_revocation_stops_and_no_automatic_retry(self):
        self.grant();c=self.launch();self.grant(enabled=False)
        out=self.drive(c['id'],until='PAUSED')
        self.assertEqual(out['status'],'PAUSED');self.assertFalse(self.calls)
        for _ in range(3):self.cycles.tick()
        self.assertFalse(self.calls)

    def test_failed_independent_candidate_never_published(self):
        self.grant();self.sources=["def transform(data):\n    return ''\n"]
        c=self.launch();out=self.drive(c['id'],until='PAUSED')
        self.assertEqual(out['status'],'PAUSED')
        self.assertIsNone(self.tools.selected(self.project['id'],c['tool_id'])['active'])
        self.assertLessEqual(len(self.calls),2)

    def test_restart_preserves_intent_without_starting_coder(self):
        self.grant();c=self.launch();self.cycles.tick()
        self.cycles=GrowthCycles(self.evolution,self.bridge)
        out=self.drive(c['id'],until='INTERRUPTED')
        self.assertEqual(out['status'],'INTERRUPTED');self.assertFalse(self.calls)
        self.assertEqual(self.cycles.start(self.cid,c['submission'])['id'],c['id'])

    def test_cancel_and_unknown_accounting_are_not_success(self):
        self.grant();c=self.launch();self.cycles.cancel(self.cid,c['id'])
        self.assertEqual(self.drive(c['id'],until='CANCELLED')['status'],'CANCELLED')
        self.assertIsNone(accounting([{'usage':{}}])['tokens'])
        self.assertIsNone(accounting([{'billing':{}}])['amount'])
        self.assertFalse(self.calls)

    def test_unknown_coder_is_not_resent(self):
        self.grant();self.sources=[None];c=self.launch()
        out=self.drive(c['id'],until='PAUSED')
        self.assertEqual(out['status'],'PAUSED');self.assertEqual(len(self.calls),1)
        self.cycles.tick();self.assertEqual(len(self.calls),1)

    def test_wrong_baseline_rejected_not_counted_as_candidate_benefit(self):
        self.grant();c=self.launch()
        def wrong(manager,job):
            return {'text':'wrong','receipt':{'status':'SUCCEEDED'}}
        with patch('jarvis_core.evolution.growth_cycle.baseline',side_effect=wrong):
            out=self.drive(c['id'],until='PAUSED')
        self.assertEqual(out['stop_reason'],'working_baseline_not_verified')
        self.assertIsNone(self.tools.selected(self.project['id'],c['tool_id'])['active'])

    def test_negative_benefit_stops_own_active_version_and_retains_package(self):
        self.grant();c=self.launch()
        assess=self.cycles.assess
        with patch('jarvis_core.evolution.growth_cycle.baseline',side_effect=self.normal_baseline),patch.object(self.cycles,'assess',side_effect=lambda x:{**assess(x),'accepted':False}):
            out=self.drive(c['id'],until='PAUSED')
        self.assertEqual(out['stop_reason'],'benefit_not_established')
        selected=self.tools.selected(self.project['id'],c['tool_id'])
        self.assertIsNone(selected['active'])
        self.assertEqual(selected['previous'],out['candidate_version'])
        self.assertEqual(self.tools.package(out['candidate_version'])[1],'VERIFIED')

    def test_expiry_validator_tamper_and_revision_fail_closed(self):
        self.grant();c=self.launch()
        c['domain']['heldout'][0]['expected']='wrong';self.cycles.save(c)
        self.assertEqual(self.drive(c['id'],until='PAUSED')['stop_reason'],'growth_validator_changed')
        self.assertFalse(self.calls)
        self.grant();c=self.launch()
        c['started_epoch']=time.time()-4000;self.cycles.save(c)
        self.assertEqual(self.drive(c['id'],until='PAUSED')['stop_reason'],'growth_authorization_changed')

    def test_revocation_at_atomic_activation_check(self):
        from jarvis_core.evolution.growth_policy import authorize
        self.grant();c=self.launch();request=self.cycles.binding(c)
        with self.evolution.store.connection() as db:authorize(db,request)
        self.grant(enabled=False)
        with self.evolution.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            with self.assertRaises(policy.CoreError):authorize(db,request)
        self.assertFalse(self.calls)

    def test_stop_intent_immediately_rejects_queued_authorization(self):
        from jarvis_core.evolution.growth_policy import authorize, check_core
        self.grant();c=self.launch();self.cycles.stop(c,'owner_cancelled','CANCELLED')
        with self.evolution.store.connection() as db:
            with self.assertRaises(policy.CoreError):authorize(db,self.cycles.binding(c))
        with self.assertRaises(policy.CoreError):check_core(self.core,self.cycles.binding(c))
        self.assertFalse(self.calls)

    def test_policy_round_budget_and_runtime_compatibility(self):
        from jarvis_core.releases import RuntimeSlots
        self.grant(maximum_cycles=1);c=self.launch();self.cycles.cancel(self.cid,c['id'])
        self.drive(c['id'],until='CANCELLED')
        with self.assertRaises(policy.CoreError):self.launch()
        self.assertTrue(RuntimeSlots._compatible('0.1.78',{'optional_versions':{'evolution/evolution.db':7}}))
        self.assertFalse(RuntimeSlots._compatible('0.1.77',{'optional_versions':{'evolution/evolution.db':7}}))
        self.assertFalse(self.calls)


for _name in dir(ProjectToolTests):
    if _name.startswith('test_') and _name not in GrowthCycleTests.__dict__:
        setattr(GrowthCycleTests,_name,None)
del ProjectToolTests

if __name__=='__main__':unittest.main()
