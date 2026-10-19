"""Real HTTP profile boundaries and metadata-only optional module observation."""
from contextlib import closing
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from jarvis_core.chat import ChatService
from jarvis_core.modules import ModuleMonitor
from jarvis_core.persona import PersonaStore
from jarvis_core.service import CoreService
from server import create_server


class PersonaHTTPTests(unittest.TestCase):
    def test_http_boundaries_optional_failure_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);sample=base/'sample';sample.mkdir();core=CoreService(base/'data');core.initialize(sample)
            server=create_server(core=core,chat=ChatService(core),port=0)
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
            origin=f'http://127.0.0.1:{server.server_port}'
            def request(method='GET',payload=None,nonce=True,site=None):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                headers={'Origin':site or origin,'Content-Type':'application/json'}
                if nonce:headers['X-Jarvis-Nonce']=server.nonce
                try:
                    conn.request(method,'/api/persona',None if method=='GET' else json.dumps(payload),headers)
                    response=conn.getresponse();return response.status,json.loads(response.read())
                finally:conn.close()
            try:
                self.assertEqual(request(nonce=False)[0],403)
                self.assertEqual(request('POST',{},site='http://example.test')[0],403)
                self.assertEqual(request('POST',None)[0],400)
                self.assertEqual(request()[1]['preferred_name'],'')
                payload={'action':'profile','revision':0,'request_id':uuid.uuid4().hex,
                    'profile':{'style':'温暖','relationship':'伙伴','preferred_name':'私密称呼'}}
                self.assertEqual(request('POST',payload)[0],200)
                self.assertTrue(request('POST',payload)[1]['replayed'])
                self.assertEqual(request('POST',{**payload,'request_id':uuid.uuid4().hex})[0],409)
                monitor=server.modules
                row=monitor._persona()[0]
                self.assertEqual(row['storage_state'],'ready');self.assertEqual(row['record_count'],1)
                self.assertNotIn('私密称呼',json.dumps(row,ensure_ascii=False))
                path=PersonaStore(core).path;original=path.read_bytes();path.write_bytes(b'corrupt temporary profile')
                self.assertEqual(request()[0],503)
                with patch.object(monitor,'_models',return_value=[]):monitor._refresh()
                rows={r['id']:r for r in monitor.cache['modules']}
                self.assertEqual(rows['persona']['health'],'unknown');self.assertEqual(rows['host']['health'],'ready')
                self.assertEqual(server.chat.reply('/计算 6*7')['status'],'SUCCEEDED')
                self.assertEqual(path.read_bytes(),b'corrupt temporary profile')
                path.write_bytes(original)
                self.assertEqual(request()[1]['preferred_name'],'私密称呼')
            finally:server.shutdown();server.server_close();thread.join(3)


if __name__=='__main__':unittest.main()
