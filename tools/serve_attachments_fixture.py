"""Offline attachment UI fixture. Echo only synthetic input; no model or vault access."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/models/provider-native')]
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_core.workspace import WorkspaceService
from jarvis_models.attachments import message_text, image_budget


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=18182)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='jarvis-attachment-ui-') as temporary:
        core=CoreService(Path(temporary)/'data');core.initialize()
        class OfflineChat(ChatService):
            def reply(self,message,attachments=None,history=None,cancel_event=None,**kwargs):
                if message.startswith('等待停止') and cancel_event:
                    cancel_event.wait(45)
                if message.startswith('模拟失败'):
                    return {'status':'FAILED','user_message':'模拟失败：用于验证草稿恢复，不调用模型。'}
                current={'content':message,'attachments':attachments or []}
                return {'status':'SUCCEEDED','provider':'fixture','model':'离线附件验收',
                    'text':'离线验收：已收到 '+str(len(attachments or []))+' 个附件，其中 '+str(image_budget([current])[1])+' 张图片。\n'+message_text(current)+'\n历史条数：'+str(len(history or [])),
                    'notice':['这是合成验收，没有调用付费模型。']}
        spec=importlib.util.spec_from_file_location('attachment_fixture_web',ROOT/'apps/web/server.py');web=importlib.util.module_from_spec(spec);spec.loader.exec_module(web)
        server=web.LocalChatServer(('127.0.0.1',args.port),core,OfflineChat(core),version='attachment-fixture',workspace=WorkspaceService(core))
        print(json.dumps({'url':f'http://127.0.0.1:{args.port}/','synthetic':True}),flush=True)
        try:server.serve_forever(poll_interval=.1)
        except KeyboardInterrupt:pass
        finally:server.server_close()


if __name__=='__main__':main()
