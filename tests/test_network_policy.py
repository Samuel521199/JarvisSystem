"""Offline control reaches dispatch, child sockets and HTTP without changing the OS."""
import asyncio
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock

import httpx
from jarvis_core.chat import ChatService, gateway
from jarvis_core.network_policy import NetworkPolicy, NetworkDenied, loopback
from jarvis_core.policy import CoreError
from jarvis_core.service import CoreService
from jarvis_core.releases import RuntimeSlots
from jarvis_models.gateway import probe, read_config
from jarvis_models.registry import Registry
from server import create_server

ROOT = Path(__file__).resolve().parents[1]


class NetworkPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        sample = self.root / 'sample'; sample.mkdir()
        self.core = CoreService(self.root / 'data'); self.core.initialize(sample)
        self.network = NetworkPolicy(self.core.data_dir)
        self.config = read_config(ROOT / 'config/model-profiles/providers.json')

    def tearDown(self):
        self.temp.cleanup()

    def test_persistence_conflict_and_fail_closed(self):
        self.assertFalse(self.network.snapshot()['offline'])
        self.assertFalse(self.network.path.exists())
        self.network.change(True, 0)
        self.assertTrue(NetworkPolicy(self.core.data_dir).snapshot()['offline'])
        with self.assertRaises(CoreError) as caught:self.network.change(False, 0)
        self.assertEqual(caught.exception.code, 'network_conflict')
        for off, rev in [(1, 1), (False, True), (False, -1)]:
            with self.assertRaises(CoreError):self.network.change(off, rev)
        self.network.change(False, 1)
        self.assertFalse(self.network.snapshot()['offline'])
        self.network.path.write_bytes(b'corrupted policy fixture')
        self.assertFalse(self.network.snapshot()['valid'])
        with self.assertRaises(NetworkDenied):self.network.require_online()
        with self.assertRaises(NetworkDenied):self.network.change(False, 2)

    def test_cloud_denied_before_credentials_or_dispatch_including_loopback_relay(self):
        self.network.change(True, 0)
        for provider in ['vertex', 'openai', 'bailian', 'xai']:
            with self.subTest(provider=provider):
                response = probe(self.config, provider, 'fixture', self.core.data_dir, self.core.assert_running,
                    credentials_loader=lambda: self.fail('credential access'),
                    client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: self.fail('transport'))))
                self.assertEqual(response['status'], 'FAILED');self.assertEqual(response['error'], 'network_offline')
                self.assertFalse(response.get('dispatch_admitted', False))
                self.assertEqual(response['billing']['amount'], 0)
        item={'adapter':'compatible','endpoint':'http://127.0.0.1:18180/v1'}
        with self.assertRaises(NetworkDenied):self.network.check_model(item,'relay')
        with patch('jarvis_models.registry.Registry.credentials',side_effect=AssertionError('vault touched')):
            with self.assertRaises(NetworkDenied):Registry(self.core.data_dir,ROOT/'config/model-profiles/providers.json').balance('eachlabs')

    def test_local_model_survives_and_fake_local_destination_rejected(self):
        self.network.change(True, 0)
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={
            'choices':[{'message':{'content':'local fixture'},'finish_reason':'stop'}]})))
        response=probe(self.config,'local','fixture',self.core.data_dir,self.core.assert_running,client=client,
                       credentials_loader=lambda:self.fail('vault touched'))
        self.assertEqual(response['status'],'SUCCEEDED')
        for endpoint in ['https://example.com/v1','http://localhost:8080/v1','http://127.0.0.1:7890/v1']:
            with self.assertRaises(NetworkDenied):self.network.check_model({'adapter':'local','endpoint':endpoint},'local')
        self.assertEqual(ChatService(self.core).reply('/计算 6*7')['status'],'SUCCEEDED')

    def test_auto_local_does_not_mutate_default_or_fallback_to_cloud(self):
        self.network.change(True,0)
        selected=[]
        def transport(config,provider,*args,**kwargs):
            selected.append(provider)
            return {'status':'FAILED','provider':provider,'model':config['providers'][provider]['model'],
                    'outcome_uncertain':False,'error_category':'provider_unavailable'}
        original=(ROOT/'config/model-profiles/providers.json').read_bytes()
        with patch('jarvis_core.chat.gateway.probe',side_effect=transport):
            result=ChatService(self.core).reply('你好',provider='auto')
        self.assertEqual(selected,['local']);self.assertEqual(result['status'],'FAILED')
        self.assertEqual((ROOT/'config/model-profiles/providers.json').read_bytes(),original)

    def test_network_change_cancels_waiting_response_and_preserves_unknown(self):
        closed=[]
        async def handler(request):
            self.network.change(True,0)
            try:await asyncio.sleep(10)
            finally:closed.append(True)
        # Use a fixture cloud endpoint and mock credential parsing. No remote call.
        with patch('jarvis_models.gateway.build_request',return_value=('https://example.test',{},{})):
            result=probe(self.config,'openai','fixture',self.core.data_dir,self.core.assert_running,
                client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),credentials_loader=lambda:{})
        self.assertEqual(result['status'],'UNKNOWN');self.assertFalse(result['automatic_retry'])
        self.assertEqual(result['error_category'],'network_offline');self.assertEqual(closed,[True])
        self.network.change(False,1)
        with self.assertRaises(NetworkDenied):self.network.require_online(0)

    def test_old_package_cannot_ignore_saved_policy(self):
        self.network.change(True,0)
        data=RuntimeSlots._data_format(self.core.data_dir)
        self.assertFalse(RuntimeSlots._compatible('0.1.62',data))
        self.assertTrue(RuntimeSlots._compatible('0.1.63',data))

    def test_browser_is_blocked_before_native_launch(self):
        from jarvis_computer.service import ComputerService
        task=json.loads((ROOT/'config/computer-use/demo-task.json').read_text(encoding='utf-8'))
        browser=MagicMock()
        self.network.change(True,0)
        service=ComputerService(self.core,browser_factory=lambda *args,**kwargs:browser)
        result=service.run(task,scripted=True,demo_html='<p>fixture</p>')
        self.assertEqual(result['action']['error']['code'],'network_offline')
        browser.start.assert_not_called()
        browser.close.assert_called_once()

    def test_real_child_audit_blocks_dns_tcp_udp_and_keeps_loopback(self):
        self.network.change(True,0)
        script=r'''
import json,socket,sys
from jarvis_core.network_policy import activate_process,NetworkDenied
activate_process(sys.argv[1]);results=[]
for action in [lambda:socket.getaddrinfo('example.com',443),lambda:socket.gethostbyname('example.com'),
               lambda:socket.gethostbyaddr('8.8.8.8'),lambda:socket.socket().connect(('192.0.2.1',443)),
               lambda:socket.socket(socket.AF_INET,socket.SOCK_DGRAM).sendto(b'x',('192.0.2.1',53)),
               lambda:socket.socket(socket.AF_INET6).connect(('::ffff:192.0.2.1',443))]:
 try:action()
 except NetworkDenied:results.append(True)
 else:results.append(False)
assert all(results)
assert socket.getaddrinfo('127.0.0.1',18180)
print(json.dumps(results))
'''
        env={**os.environ,'PYTHONPATH':str(ROOT/'runtime/node-host')}
        result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,str(self.core.data_dir)],env=env,
                              capture_output=True,text=True,encoding='utf-8',timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),[True]*6)
        for host in ['127.0.0.1','::1','::ffff:127.0.0.1','localhost']:self.assertTrue(loopback(host))
        for host in ['localhost.example.com','192.168.1.1','::ffff:8.8.8.8']:self.assertFalse(loopback(host))

    def test_http_nonce_busy_conflict_and_local_controls(self):
        server=create_server(core=self.core,chat=ChatService(self.core),port=0)
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        def request(method='GET',body=None,nonce=True,path='/api/network'):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=4)
            headers={'Origin':f'http://127.0.0.1:{server.server_port}','Content-Type':'application/json'}
            if nonce:headers['X-Jarvis-Nonce']=server.nonce
            try:
                conn.request(method,path,None if body is None else json.dumps(body),headers)
                response=conn.getresponse();return response.status,json.loads(response.read())
            finally:conn.close()
        try:
            self.assertEqual(request(nonce=False)[0],403)
            self.assertEqual(request('POST',{'offline':'true','revision':0})[0],400)
            server.chat_requests.active=1
            self.assertEqual(request('POST',{'offline':True,'revision':0})[0],409)
            server.chat_requests.active=0
            self.assertEqual(request('POST',{'offline':True,'revision':0})[0],200)
            self.assertTrue(request()[1]['offline'])
            self.assertEqual(request('POST',{'offline':False,'revision':0})[0],409)
            self.assertEqual(server.chat.reply('/计算 21*2')['status'],'SUCCEEDED')
            self.assertEqual(request('POST',{'offline':False,'revision':1})[0],200)
        finally:server.shutdown();server.server_close();thread.join(3)


if __name__=='__main__':unittest.main()
