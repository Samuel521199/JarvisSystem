"""Actual paired loopback TLS, independent stores, explicit receiver grants."""
import copy
from contextlib import closing
import json
import sqlite3
import sys
import threading
import unittest
import uuid
from unittest.mock import patch

import test_federation as fixture
from jarvis_core import federation_protocol as p
from jarvis_core import federation_scoped as scoped
from jarvis_core.federation import Federation
from jarvis_core.federation_access import destination
from jarvis_core.memory import MemoryStore
from jarvis_core.policy import CoreError
from jarvis_core.workspace import WorkspaceService


class ScopedTests(unittest.TestCase):
    setUp = fixture.FederationTests.setUp
    pair = fixture.FederationTests.pair
    state = fixture.FederationTests.state
    edit = fixture.FederationTests.edit
    card = fixture.FederationTests.card

    def fact(self, node, project=None, text='喜欢简洁的中文回答', ident=None, revision=0):
        ident=ident or uuid.uuid4().hex
        MemoryStore(node.core).put(ident,{'revision':revision,'document':{
            'title':'合成记忆','content':text,'project_id':project,'providers':[]}})
        return ident

    def project(self, node, name):
        path=self.root/name;path.mkdir()
        return WorkspaceService(node.core).open_project({'path':str(path)})['id']

    def configure(self,node,rows=None,grants=None):
        s=scoped.state(self.state(node))
        if rows is None:rows=list(s['selected'].values())
        rows=[{k:r[k] for k in ('kind','source','source_project','expected')} for r in rows]
        return node.scoped.configure(self.sid,s['revision'],rows,s['grants'] if grants is None else grants)

    def select(self,node,ident,project=None,kind='memory'):
        row=next(r for r in node.scoped.options(self.sid,kind,project)['sources'] if r['id']==ident)
        return dict(kind=kind,source=ident,source_project=project,expected=row['expected'])

    def enable(self):
        self.configure(self.a,[]);self.configure(self.b,[])

    def grant(self,node,project=None,ids=None):
        catalog=scoped.state(self.state(node))['catalog']
        return {item:{'domain':r['domain'],'source_project':r['source_project'],
                      'project_id':project if r['domain']=='project' else None}
                for item,r in catalog.items() if ids is None or item in ids}

    def prepared(self,project=False):
        self.pair();self.enable()
        pa=self.project(self.a,'alpha') if project else None
        pb=self.project(self.b,'beta') if project else None
        ident=self.fact(self.a,pa)
        self.configure(self.a,[self.select(self.a,ident,pa)])
        self.b.scoped.sync(self.sid)
        self.configure(self.b,grants=self.grant(self.b,pb))
        self.b.scoped.sync(self.sid,True)
        return ident,pa,pb

    def inbox(self,node):
        return scoped.state(self.state(node))['inbox']

    def test_default_no_creation_and_enable_blocks_legacy(self):
        self.assertFalse(self.a.status()['initialized'])
        self.assertFalse((self.a.core.data_dir/'memory.db').exists())
        self.pair();self.enable()
        with self.assertRaises(CoreError):self.b.sync(self.sid)
        self.assertFalse((self.a.core.data_dir/'memory.db').exists())

    def test_catalog_and_default_denial_never_send_body(self):
        self.pair();self.enable();ident=self.fact(self.a,text='SECRET_BODY_NOT_IN_CATALOG')
        self.configure(self.a,[self.select(self.a,ident)])
        original=self.a.scoped.receive;wire=[]
        def capture(value):
            response=original(value);wire.append((value,response));return response
        with patch.object(self.a.scoped,'receive',side_effect=capture):
            self.b.scoped.sync(self.sid,True)
        self.assertNotIn('SECRET_BODY_NOT_IN_CATALOG',json.dumps(wire))
        self.assertTrue(scoped.state(self.state(self.b))['catalog'])
        self.assertFalse(self.inbox(self.b))

    def test_selected_personal_fact_only_and_source_update_forget(self):
        ident,_,_=self.prepared()
        self.assertEqual(len(self.inbox(self.b)),1)
        self.assertFalse((self.b.core.data_dir/'memory.db').exists())
        self.fact(self.a,text='更新的中文偏好',ident=ident,revision=1)
        self.b.scoped.sync(self.sid,True)
        self.assertIn('更新的中文偏好',json.dumps(self.inbox(self.b),ensure_ascii=False))
        MemoryStore(self.a.core).delete(ident,{'revision':2})
        self.b.scoped.sync(self.sid,True)
        self.assertFalse(self.inbox(self.b))

    def test_project_mapping_and_model_scope_are_enforced(self):
        _,pa,pb=self.prepared(True);card=scoped.received_cards(self.state(self.b))[0]
        self.assertNotEqual(pa,pb)
        with self.assertRaises(CoreError):scoped.received_body(self.state(self.b),card['id'],None)
        self.assertTrue(scoped.received_body(self.state(self.b),card['id'],pb))
        with self.assertRaises(CoreError):scoped.received_body(self.state(self.b),card['id'],pa)

    def test_grant_revoke_clears_body_and_stale_reference(self):
        self.prepared();card=scoped.received_cards(self.state(self.b))[0]
        config=self.b.access.config();target=destination(config,'local')
        self.b.access.change(self.sid,0,[card['id']],{'local':target},None)
        scope={'conversation_id':uuid.uuid4().hex,'project_id':None}
        ref=self.b.access.issue(self.sid,card['id'],card['expected'],scope)['reference']
        self.b.access.recheck(scope,[ref],config,'local')
        self.configure(self.b,grants={})
        self.assertFalse(self.inbox(self.b))
        with self.assertRaises(CoreError):self.b.access.recheck(scope,[ref],config,'local')
        self.b.scoped.sync(self.sid,True);self.assertFalse(self.inbox(self.b))

    def test_source_cloud_permission_not_expanded_by_receiver(self):
        self.prepared();card=scoped.received_cards(self.state(self.b))[0]
        with self.assertRaises(CoreError):
            scoped.received_body(self.state(self.b),card['id'],None,'openai','f'*64)

    def test_inflight_revocation_rejects_reply(self):
        self.prepared()
        from jarvis_core import federation_scoped as module
        original=module.exchange
        def revoke(*args,**kwargs):
            result=original(*args,**kwargs)
            if args[3]['body']['operation']=='transfer':self.configure(self.b,grants={})
            return result
        with patch.object(module,'exchange',side_effect=revoke),self.assertRaises(CoreError):
            self.b.scoped.sync(self.sid,True)
        self.assertFalse(self.inbox(self.b))

    def test_unpermitted_or_tampered_incoming_rejected(self):
        self.prepared();s=self.state(self.b);before=copy.deepcopy(s)
        value=scoped.state(s)
        row=next(iter(value['inbox'].values()))['signed']
        for incoming in ({uuid.uuid4().hex:row},{next(iter(value['inbox'])):{**row,'signature':'bad'}}):
            with self.assertRaises(CoreError):
                self.b.scoped.apply(s,dict(receiver_revision=value['revision'],seq=value['peer_seq']+1,
                                          items=incoming,catalog=value['catalog']),value['revision'])
        self.assertEqual(self.state(self.b),before)

    def test_stale_policy_and_invalid_domain_mapping(self):
        self.prepared()
        with self.assertRaises(CoreError):self.b.scoped.configure(self.sid,0,[],{})
        grants=self.grant(self.b);next(iter(grants.values()))['project_id']=uuid.uuid4().hex
        with self.assertRaises(CoreError):self.configure(self.b,grants=grants)

    def test_offline_no_network_and_restart_retains_grants(self):
        self.prepared();before=self.inbox(self.b)
        self.b.network.change(True,0)
        with patch('jarvis_core.federation_scoped.exchange') as mock,self.assertRaises(CoreError):
            self.b.scoped.sync(self.sid,True)
        mock.assert_not_called()
        self.b.network.change(False,1)
        reopened=Federation(self.b.core);self.addCleanup(reopened.close)
        reopened.scoped.sync(self.sid,True)
        self.assertEqual(len(self.inbox(reopened)),len(before))
        self.assertIsNone(reopened.status()['endpoint'])

    def test_archive_restore_keeps_data_without_grants(self):
        self.prepared();preview=self.b.lifecycle.preview(self.sid)
        self.b.lifecycle.archive(self.sid,preview['expected']);self.b.lifecycle.restore(self.sid)
        self.assertEqual(len(scoped.received_cards(self.state(self.b))),1)
        self.assertFalse(scoped.state(self.state(self.b))['grants'])
        self.assertFalse(scoped.state(self.state(self.b))['selected'])
        with self.assertRaises(CoreError):self.b.scoped.sync(self.sid,True)

    def test_bilateral_selected_cards(self):
        self.pair();self.enable()
        a=self.edit(self.a,text='A_CARD');b=self.edit(self.b,text='B_CARD')
        self.configure(self.a,[self.select(self.a,a,kind='card')])
        self.configure(self.b,[self.select(self.b,b,kind='card')])
        self.b.scoped.sync(self.sid)
        self.configure(self.a,grants=self.grant(self.a));self.configure(self.b,grants=self.grant(self.b))
        self.b.scoped.sync(self.sid,True)
        self.assertIn('B_CARD',json.dumps(self.inbox(self.a)))
        self.assertIn('A_CARD',json.dumps(self.inbox(self.b)))
        self.assertEqual(set(self.state(self.a)['items']),{a})

    def test_unchanged_sync_keeps_reference_but_regrant_does_not(self):
        self.prepared();first=scoped.received_cards(self.state(self.b))[0]['expected']
        self.b.scoped.sync(self.sid,True)
        self.assertEqual(scoped.received_cards(self.state(self.b))[0]['expected'],first)
        grants=self.grant(self.b)
        self.configure(self.b,grants={});self.configure(self.b,grants=grants)
        self.b.scoped.sync(self.sid,True)
        self.assertNotEqual(scoped.received_cards(self.state(self.b))[0]['expected'],first)

    def test_withdraw_and_republish_cannot_revive_old_reference(self):
        ident,_,_=self.prepared()
        first=scoped.received_cards(self.state(self.b))[0]['expected']
        self.configure(self.a,[]);self.b.scoped.sync(self.sid,True)
        self.assertFalse(self.inbox(self.b))
        self.configure(self.a,[self.select(self.a,ident)]);self.b.scoped.sync(self.sid,True)
        self.assertNotEqual(scoped.received_cards(self.state(self.b))[0]['expected'],first)

    def test_schema_four_rejects_older_managed_runtime(self):
        self.prepared()
        with closing(sqlite3.connect(self.b.core.data_dir/'federation.db')) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],4)
        from jarvis_core.releases import RuntimeSlots
        fmt={'optional_versions':{'federation.db':4}}
        for version in ('0.1.83','0.1.84','0.1.85','0.1.86'):
            self.assertFalse(RuntimeSlots._compatible(version,fmt))
        self.assertTrue(RuntimeSlots._compatible('0.1.87',fmt))

    def test_project_remap_clears_body_until_next_sync(self):
        _,_,old=self.prepared(True);new=self.project(self.b,'new-project')
        grants=self.grant(self.b,new);self.configure(self.b,grants=grants)
        self.assertFalse(self.inbox(self.b))
        self.b.scoped.sync(self.sid,True)
        card=scoped.received_cards(self.state(self.b))[0]
        self.assertEqual(card['project_id'],new)
        with self.assertRaises(CoreError):scoped.received_body(self.state(self.b),card['id'],old)

    def test_source_scope_change_withdraws_original_publication(self):
        ident,_,_=self.prepared();project=self.project(self.a,'moved-fact')
        self.fact(self.a,project,text='项目事实',ident=ident,revision=1)
        self.b.scoped.sync(self.sid,True)
        self.assertFalse(self.inbox(self.b))

    def test_snapshot_rollback_and_expiry_are_rejected(self):
        self.prepared();s=self.state(self.b);value=scoped.state(s)
        with self.assertRaises(CoreError):
            self.b.scoped.apply(s,dict(receiver_revision=value['revision'],seq=value['peer_seq']-1,
                                      items={},catalog={}),value['revision'])
        item,row=next(iter(value['inbox'].items()))
        signed=copy.deepcopy(row['signed']);signed['body']['expires_at']='2000-01-01T00:00:00Z'
        row['signed']=p.sign(signed['body'],self.a._identity().load().key)
        with self.assertRaises(CoreError):scoped.received_body(s,scoped.virtual_id(s,item),None)

    def test_real_model_worker_uses_only_granted_received_memory(self):
        ident,_,_=self.prepared()
        self.fact(self.a,text='SYNTHETIC_SHARED_DATA_85: 合成共享偏好',ident=ident,revision=1)
        self.b.scoped.sync(self.sid,True)
        card=scoped.received_cards(self.state(self.b))[0];config=self.b.access.config()
        self.b.access.change(self.sid,0,[card['id']],{'local':destination(config,'local')},None)
        scope={'conversation_id':uuid.uuid4().hex,'project_id':None}
        ref=self.b.access.issue(self.sid,card['id'],card['expected'],scope)['reference']
        from jarvis_core.chat import ChatService
        from jarvis_core.dialogue_process import DialogueProcesses
        from jarvis_core.turns import invoke_reply
        chat=ChatService(self.b.core,self.b.access.config_path)
        pool=DialogueProcesses(self.b.core);self.addCleanup(pool.close)
        pool._command=[sys._base_executable,'-u',str(fixture.ROOT/'tests/shared_dialogue_fixture.py'),'normal']
        chat.dialogue_models=pool
        request={'message':'请说明引用资料','provider':'local','shared_context':{'scope':scope,'references':[ref]}}
        result=invoke_reply(self.b.core,chat,request,threading.Event(),scope['conversation_id'])
        self.assertEqual(result.get('text'),'共享资料测试回答',result)
        self.assertTrue(result['history_info']['shared']['used'])
        self.configure(self.b,grants={})
        denied=invoke_reply(self.b.core,chat,request,threading.Event(),scope['conversation_id'])
        self.assertNotIn('text',denied)
        self.assertEqual(pool.snapshot()['active'],0)

    def test_project_only_card_model_permission_is_not_personal_permission(self):
        self.pair();self.enable();project=self.project(self.a,'card-project')
        item=self.edit(self.a);config=self.a.access.config()
        self.a.access.change(self.sid,0,[item],{'local':destination(config,'local')},project)
        self.configure(self.a,[self.select(self.a,item,kind='card')])
        self.b.scoped.sync(self.sid)
        self.configure(self.b,grants=self.grant(self.b));self.b.scoped.sync(self.sid,True)
        signed=next(iter(self.inbox(self.b).values()))['signed']
        self.assertFalse(signed['body']['model_targets'])


if __name__=='__main__':unittest.main()
