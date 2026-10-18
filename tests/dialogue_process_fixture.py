"""Synthetic process faults, selected only by tests; no production fault switch."""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime/node-host'))
mode = sys.argv[1]
if mode == 'parent_exit':
    import threading
    from jarvis_core.service import CoreService
    from jarvis_core.dialogue_process import DialogueProcesses
    request=json.loads(sys.stdin.buffer.read())
    core=CoreService(request['data_dir']); pool=DialogueProcesses(core)
    pool._command=[sys._base_executable,'-u',__file__,'hang']
    thread=threading.Thread(target=lambda:pool.probe(request['config'],'local','test',core.data_dir,core.assert_running))
    thread.start()
    end=time.monotonic()+5
    while time.monotonic()<end:
        state=pool.snapshot()
        if state['active']:
            print(state['processes'][0]['pid'],flush=True)
            os._exit(31)
        time.sleep(.01)
    os._exit(32)
if mode in {'gateway','context_hang','plan_gateway','model_hang','intent_gateway','intent_invalid'}:
    # Exercise the real gateway, admission and usage journal without a network.
    from jarvis_core.chat import gateway
    if mode in {'intent_gateway','intent_invalid'}:
        from jarvis_core import intent
        intent.supported = lambda provider, model: True
    import httpx
    import asyncio
    if mode=='context_hang':
        from jarvis_core.memory_view import MemoryView
        MemoryView.snapshot=lambda *a,**kw:time.sleep(120)
    original = httpx.AsyncClient
    async def transport(request):
        if mode=='model_hang': await asyncio.sleep(120)
        text='isolated gateway reply'
        if mode=='intent_gateway':
            text=json.dumps({'schema_version':1,'reply':'我在这里陪你。文档查询还没有提交，可以先核对草稿。',
                'interaction_style':'empathetic','intents':[
                    {'kind':'emotion','quote':'我有点难过，陪我聊聊','disposition':'requested','capability':None,'arguments':{},'missing_fields':[]},
                    {'kind':'action','quote':'查询 Electron 文档中的 ipcMain.handle 示例','disposition':'requested',
                     'capability':'mcp.documentation','arguments':{'library':'Electron','query':'ipcMain.handle 示例'},'missing_fields':[]}]},ensure_ascii=False)
        if mode=='intent_invalid':text='{"schema_version":1,"reply":'
        if mode=='plan_gateway':
            text=json.dumps({'schema_version':1,'kind':'inventory_report','steps':[
                {'skill':'sample_metadata_read','arguments':{'relative_path':'.'}},
                {'skill':'artifact_output','arguments':{'format':'json'}}]})
        return httpx.Response(200,json={'choices':[{'message':{'content':text},'finish_reason':'stop'}],
                                       'usage':{'prompt_tokens':5,'completion_tokens':3}})
    def client(**kwargs):
        kwargs['transport'] = httpx.MockTransport(transport)
        return original(**kwargs)
    gateway.httpx.AsyncClient = client
    from jarvis_core.dialogue_worker import main
    sys.exit(main())
packet = json.loads(sys.stdin.buffer.read())
if mode == 'hang': time.sleep(120)
if mode == 'crash': os._exit(23)
if mode == 'oversize':
    sys.stdout.buffer.write(b'x' * (2 * 1024 * 1024 + 100)); sys.stdout.buffer.flush(); time.sleep(120)
if mode == 'invalid':
    print('not JSON'); sys.exit(0)
print(json.dumps({'id': 'wrong' if mode == 'wrong_id' else packet['id'],
                  'result': {'status': 'SUCCEEDED', 'text': 'child reply', 'outcome_uncertain': False}}))
