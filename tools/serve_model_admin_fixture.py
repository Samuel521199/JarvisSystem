"""Isolated administration UI fixture: synthetic usage, in-memory keys, no paid calls."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/models/provider-native')]
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_models.registry import Registry, effective_config
from jarvis_models.gateway import ProbeJournal
from jarvis_models.billing import estimate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=18182)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='jarvis-admin-ui-') as temporary:
        data=Path(temporary)/'data';core=CoreService(data);core.initialize()
        class OfflineChat(ChatService):
            def reply(self,*args,**kwargs):
                return {'status':'FAILED','user_message':'这是离线界面验收，不发送模型请求。'}
        credentials={}
        def save(value):credentials.clear();credentials.update(value)
        registry=Registry(data,ROOT/'config/model-profiles/providers.json',loader=lambda:json.loads(json.dumps(credentials)),saver=save,vault_exists=lambda:True)
        for route in ('eachlabs','openai','xai','bailian'):
            registry.mutate(dict(revision=registry.snapshot()['revision'],action='add_key',connection=route,label='验收用 Key',secret='synthetic-ui-key-0000'))
        config=effective_config(ROOT/'config/model-profiles/providers.json',data)
        journal=ProbeJournal(data/'model-probes.db')
        for day in range(7):
            for index,route in enumerate(('eachlabs','openai','vertex','bailian')):
                item=config['providers'][route];mid=item['model'];kid=item.get('credential_id')
                usage={'input_tokens':(day+3)*17000+index*4000,'output_tokens':(8-day)*4000}
                bill=estimate('openai',usage,item['models'][mid].get('price'))
                ident=journal.reserve(route,mid,'synthetic UI fixture')
                journal.finish(ident,'SUCCEEDED',{'usage':usage,'billing':bill,'billing_identity':{'key_id':kid,'key_label':'验收用 Key','label':item['label']}})
                stamp=(datetime.now(timezone.utc)-timedelta(days=day)).replace(hour=4,minute=30).isoformat()
                with closing(journal.connect()) as db,db:db.execute('UPDATE probes SET created_at=? WHERE id=?',(stamp,ident))
        journal.finish(journal.reserve('eachlabs','anthropic/claude-sonnet-5.5','fixture unknown'),'UNKNOWN',{})
        spec=importlib.util.spec_from_file_location('admin_fixture_web',ROOT/'apps/web/server.py');web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
        server=web.LocalChatServer(('127.0.0.1',args.port),core,OfflineChat(core),version='fixture')
        from jarvis_core.workspace import WorkspaceService
        sys.path.insert(0,str(ROOT/'adapters/computer-use'))
        from jarvis_computer.web import ComputerWeb
        server.workspace=WorkspaceService(core)
        server.computer=ComputerWeb(core,server.chat)
        server.admin=registry
        server.admin_html=server.admin_html.replace('模型控制台'.encode(), '模型控制台 · 合成验收'.encode())
        # This fixture never contacts an account even if the balance button is clicked.
        def no_balance(_):raise ValueError('离线验收不访问供应商余额。')
        registry.balance=no_balance
        print(json.dumps({'url':f'http://127.0.0.1:{args.port}/admin','synthetic':True}),flush=True)
        try:server.serve_forever(poll_interval=.1)
        except KeyboardInterrupt:pass
        finally:server.server_close()


if __name__=='__main__':main()
