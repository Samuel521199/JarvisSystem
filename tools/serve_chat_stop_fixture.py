"""Disposable loopback fixture for manual/automated Stop-button UI checks.

Uses the real ChatService and HTTPX cancellation path with synthetic transport.
No credentials or network model requests. Exit with Ctrl+C after inspecting UI.
"""
import asyncio
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core.chat import ChatService, gateway
from jarvis_core.service import CoreService
import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(os.environ['LOCALAPPDATA'])/'Jarvis/data/diagnostics/chat-stop')
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='jarvis-chat-stop-ui-') as directory:
        base = Path(directory);project = base/'停止按钮验证';project.mkdir()
        core = CoreService(base/'data');core.initialize(project)
        config = json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        config.update(default_provider='local', automatic_fallback=False)
        config_path=base/'providers.json';config_path.write_text(json.dumps(config),encoding='utf-8')
        state={'calls':0,'transport_cancelled':0,'completed':0,'project':str(project)}
        lock=threading.Lock()
        def record(key):
            with lock:
                state[key]+=1
                (output/'fixture-state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        async def handler(request):
            prompt=json.loads(request.content)['messages'][-1]['content']
            record('calls')
            if prompt.startswith('立即'):
                record('completed')
                return httpx.Response(200,json={'choices':[{'message':{'content':'新的请求已正常完成。'}}]})
            try:
                await asyncio.sleep(45)
                record('completed')
                return httpx.Response(200,json={'choices':[{'message':{'content':'迟到回答不应在停止后出现。'}}]})
            except asyncio.CancelledError:
                record('transport_cancelled')
                raise
        original=gateway.probe
        def offline_probe(*args,**kwargs):
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
            try:return original(*args,**kwargs,client=client,credentials_loader=lambda:(_ for _ in ()).throw(AssertionError('No real credentials')))
            finally:asyncio.run(client.aclose())
        spec=importlib.util.spec_from_file_location('stop_fixture_web',ROOT/'apps/web/server.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.object(gateway,'probe',side_effect=offline_probe):
            server=module.create_server(core=core,chat=ChatService(core,config_path),port=18182)
            registered=server.workspace.open_project({'path':str(project)})
            url='http://127.0.0.1:18182/#project='+registered['id']
            state['url']=url
            (output/'fixture-state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps({'url':url,'project':str(project),'evidence':str(output)},ensure_ascii=False),flush=True)
            try:server.serve_forever(poll_interval=.1)
            except KeyboardInterrupt:pass
            finally:
                server.server_close()
                state['files']=[p.name for p in project.iterdir()]
                state['outputs']=server.workspace.outputs()['outputs']
                state['core_stopped']=core.status()['stopped']
                (output/'fixture-state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
