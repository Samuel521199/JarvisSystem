"""Scoped shared-data use with real local identities, never owner model credentials."""
import copy
import json
import time
import unittest
from unittest.mock import patch
import uuid

import test_federation as fixtures
from jarvis_core import federation_protocol as p
from jarvis_core.chat import ChatService
from jarvis_core.policy import CoreError
from jarvis_core.federation_access import context, destination


class AccessTests(unittest.TestCase):
    setUp = fixtures.FederationTests.setUp
    pair = fixtures.FederationTests.pair
    state = fixtures.FederationTests.state
    card = fixtures.FederationTests.card
    edit = fixtures.FederationTests.edit

    def ready(self, providers=('vertex',), project=None):
        self.pair()
        self.item = self.edit(self.a, text='SYNTHETIC_SHARED_DATA_85: 另一人的资料，不是主人偏好')
        self.config = json.loads((fixtures.ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        self.config.update(default_provider='vertex', automatic_fallback=True, fallback_order=['openai', 'local'])
        self.config_path = self.root/'models.json'
        self.config_path.write_text(json.dumps(self.config), encoding='utf-8')
        self.a.access.config_path = self.config_path
        self.scope = {'conversation_id':uuid.uuid4().hex, 'project_id':project}
        self.grant(providers, project)
        self.token = self.issue()
        self.chat = ChatService(self.a.core, self.config_path)
        return {'scope':self.scope, 'references':[self.token]}

    def grant(self, providers=(), project=None, cards=None):
        revision = self.state(self.a).get('model_access', {}).get('revision', 0)
        return self.a.access.change(self.sid, revision, cards if cards is not None else [self.item],
                                   {v:destination(self.config,v) for v in providers}, project)

    def issue(self):
        return self.a.access.issue(self.sid, self.item, p.heads_token(self.card(self.a,self.item)), self.scope)['reference']

    def success(self, config, provider, message, data_dir, guard, **kwargs):
        with kwargs['admission_context']():
            guard()
        return {'status':'SUCCEEDED','provider':provider,'model':config['providers'][provider]['model'],
                'text':'合成模型回答','dispatch_admitted':True,'usage':{'output_tokens':2}}

    def test_default_deny_scoped_grant_and_peer_policy_is_independent(self):
        self.pair(); self.item=self.edit(self.a)
        self.scope={'conversation_id':uuid.uuid4().hex,'project_id':None}
        with self.assertRaises(CoreError): self.issue()
        config=json.loads((fixtures.ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        self.a.access.change(self.sid,0,[self.item],{'vertex':destination(config,'vertex')},None)
        self.b.sync(self.sid)
        self.assertNotIn('model_access',self.state(self.b))
        self.assertNotIn('model_access',p.snapshot(self.state(self.a),self.a.node))
        with self.assertRaises(CoreError):
            self.b.access.issue(self.sid,self.item,p.heads_token(self.card(self.b,self.item)),self.scope)

    def test_issue_is_signed_reference_without_materialized_body(self):
        ctx=self.ready()
        self.assertNotIn('SYNTHETIC_SHARED',json.dumps(ctx))
        p.verify(self.token,self.a._identity().pem)
        with self.assertRaises(CoreError):
            self.a.access.issue(self.sid,uuid.uuid4().hex,p.heads_token([]),self.scope)
        before=self.state(self.a)['model_access']
        with self.assertRaises(CoreError): self.a.access.change(self.sid,0,[],{},None)
        self.assertEqual(self.state(self.a)['model_access'],before)

    def test_tamper_scope_and_expiry_rejected(self):
        ctx=self.ready()
        for field,value in [('item',uuid.uuid4().hex),('expected','0'*64)]:
            bad=copy.deepcopy(ctx);bad['references'][0]['body'][field]=value
            with self.assertRaises(CoreError): self.a.access.prepare(bad,[],[],self.config,'vertex')
        for changed_scope in ({**self.scope,'conversation_id':uuid.uuid4().hex},
                              {**self.scope,'project_id':uuid.uuid4().hex}):
            with self.assertRaises(CoreError):
                self.a.access.prepare({**ctx,'scope':changed_scope},[],[],self.config,'vertex')
        with patch('jarvis_core.federation_access.time.time',return_value=time.time()+86401):
            with self.assertRaises(CoreError): self.a.access.prepare(ctx,[],[],self.config,'vertex')

    def test_route_specific_dispatch_and_no_model_credentials_for_unauthorized_route(self):
        ctx=self.ready(('openai',))
        with patch('jarvis_core.chat.gateway.probe',side_effect=self.success) as probe:
            result=self.chat.reply('概括所选资料',shared_context=ctx)
        self.assertEqual(result['status'],'SUCCEEDED')
        self.assertEqual(probe.call_count,1);self.assertEqual(probe.call_args.args[1],'openai')
        self.assertIn('SYNTHETIC_SHARED',probe.call_args.kwargs['attachments'][0]['text'])
        self.assertEqual(result['history_info']['shared']['references'],[self.token])

    def test_updated_deleted_conflicted_or_archived_card_is_not_dispatched(self):
        ctx=self.ready()
        self.edit(self.a,self.item,text='新的资料')
        with patch('jarvis_core.chat.gateway.probe') as probe:
            result=self.chat.reply('概括所选资料',provider='vertex',shared_context=ctx)
            self.assertEqual(result['status'],'FAILED');probe.assert_not_called()
        self.token=self.issue();ctx['references']=[self.token]
        self.edit(self.a,self.item,deleted=True)
        with self.assertRaises(CoreError): self.a.access.prepare(ctx,[],[],self.config,'vertex')
        plan=self.a.lifecycle.preview(self.sid);self.a.lifecycle.archive(self.sid,plan['expected'])
        self.a.lifecycle.restore(self.sid)
        self.assertNotIn('model_access',self.state(self.a))
        with self.assertRaises(CoreError): self.a.access.prepare(ctx,[],[],self.config,'vertex')

    def test_fallback_rechecks_grant_after_first_provider_rejects(self):
        ctx=self.ready(('vertex','openai'))
        def first(*args,**kwargs):
            self.grant(())
            return {'status':'FAILED','error_category':'quota_exhausted','dispatch_admitted':True}
        with patch('jarvis_core.chat.gateway.probe',side_effect=first) as probe:
            result=self.chat.reply('概括所选资料',shared_context=ctx)
        self.assertEqual(probe.call_count,1);self.assertNotIn('text',result)

    def test_inflight_revoke_withholds_answer_and_preserves_usage(self):
        ctx=self.ready()
        def late(*args,**kwargs):
            result=self.success(*args,**kwargs);self.grant(());return result
        with patch('jarvis_core.chat.gateway.probe',side_effect=late):
            result=self.chat.reply('概括所选资料',provider='vertex',shared_context=ctx)
        self.assertEqual(result['status'],'UNKNOWN')
        self.assertEqual(result['usage']['output_tokens'],2);self.assertNotIn('text',result)

    def test_context_to_admission_race_cannot_bypass_grant_guard(self):
        ctx=self.ready()
        def phase(name):
            if name=='model':self.grant(())
        self.chat.phase_hook=phase
        admitted=[]
        def send(*args,**kwargs):
            result=self.success(*args,**kwargs);admitted.append(True);return result
        with patch('jarvis_core.chat.gateway.probe',side_effect=send):
            result=self.chat.reply('概括所选资料',provider='vertex',shared_context=ctx)
        self.assertFalse(admitted);self.assertNotIn('text',result)

    def test_history_dependencies_are_transitive_and_revocation_drops_whole_turn(self):
        ctx=self.ready()
        history=[{'role':'user','content':'之前的问题'},{'role':'assistant','content':'SYNTHETIC_DERIVED_SECRET'}]
        follow={'scope':self.scope,'references':[]}
        with patch('jarvis_core.chat.gateway.probe',side_effect=self.success) as probe:
            result=self.chat.reply('继续解释',provider='vertex',shared_context=follow,
                                   history=history,history_shared=[[],[self.token]])
            self.assertEqual(result['history_info']['shared']['references'],[self.token])
            self.assertEqual(len(probe.call_args.kwargs['history']),2)
            self.grant(())
            result=self.chat.reply('继续聊天',provider='vertex',shared_context=follow,
                                   history=history,history_shared=[[],[self.token]])
            self.assertEqual(probe.call_args.kwargs['history'],[])
            self.assertEqual(result['history_info']['shared']['dropped_history_messages'],2)
            self.assertFalse(result['history_info']['shared']['used'])

    def test_project_scope_is_exact_and_route_target_change_requires_new_grant(self):
        ctx=self.ready(('bailian',))
        from jarvis_core.workspace import WorkspaceService
        project=WorkspaceService(self.a.core).open_project({'path':str(self.root/'source')})['id']
        self.grant(('bailian',),project)
        with self.assertRaises(CoreError): self.issue()
        self.scope['project_id']=project;ctx={'scope':self.scope,'references':[self.issue()]}
        self.config['providers']['bailian']['region']='singapore'
        self.config_path.write_text(json.dumps(self.config),encoding='utf-8')
        with self.assertRaises(CoreError): self.a.access.prepare(ctx,[],[],self.config,'bailian')

    def test_conflict_blocks_current_reference_and_malformed_context_fails(self):
        ctx=self.ready();self.b.sync(self.sid)
        self.edit(self.a,self.item,text='a');self.edit(self.b,self.item,text='b');self.b.sync(self.sid)
        with self.assertRaises(CoreError):self.a.access.prepare(ctx,[],[],self.config,'vertex')
        for value in ({'scope':self.scope,'references':[self.token]*9},
                      {'scope':None,'references':[self.token]}):
            with self.assertRaises(CoreError):context(value)
        with self.assertRaises(CoreError):context(ctx,[{}],[])

    def test_schema_three_rejects_old_managed_runtime(self):
        from jarvis_core.releases import RuntimeSlots
        for version in ('0.1.83','0.1.84'):
            self.assertFalse(RuntimeSlots._compatible(version,{'optional_versions':{'federation.db':3}}))
        self.assertTrue(RuntimeSlots._compatible('0.1.85',{'optional_versions':{'federation.db':3}}))


if __name__=='__main__':
    unittest.main()
