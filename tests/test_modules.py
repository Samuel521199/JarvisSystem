"""Module observability and maintenance must not consume the chat execution lane."""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'runtime/node-host'),str(ROOT/'adapters/models/provider-native')]
from tests import test_web
from jarvis_core.modules import ModuleMonitor, ModuleError
from jarvis_core.releases import RuntimeSlots


class ModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.core=test_web.FakeCore();self.core.data_dir=self.root
        self.monitor=ModuleMonitor(self.core,lambda:{'chat':0,'computer':False,'tasks':[],
                                   'memory':True,'knowledge':True,'extensions':True,'personal':True},
                                   model_root=self.root/'models',releases_root=self.root/'releases')
        self.addCleanup(self.monitor.close)

    def wait_job(self):
        end=time.monotonic()+5
        while self.monitor.job and time.monotonic()<end:time.sleep(.01)
        self.assertIsNone(self.monitor.job)
        return self.monitor.jobs[-1]

    def test_snapshot_nonblocking_singleflight_and_close(self):
        entered=threading.Event();release=threading.Event()
        def collect():entered.set();release.wait(3)
        with patch.object(self.monitor,'_refresh',side_effect=collect) as observer:
            self.monitor.snapshot();self.assertTrue(entered.wait(1))
            start=time.monotonic()
            for _ in range(20):self.assertTrue(self.monitor.snapshot(refresh=True)['refreshing'])
            self.assertLess(time.monotonic()-start,.3);self.assertEqual(observer.call_count,1)
            self.monitor.close();release.set()

    def test_one_failed_collector_keeps_other_observations_and_no_cloud_call(self):
        with patch.object(self.monitor,'_models',side_effect=RuntimeError('sensitive')):
            self.monitor._refresh()
        rows={r['id']:r for r in self.monitor.cache['modules']}
        self.assertEqual(rows['models']['health'],'unknown')
        self.assertEqual(rows['local-llm']['health'],'unknown');self.assertEqual(len(rows),25)
        self.assertEqual(rows['calculator']['health'],'ready')
        self.assertTrue(rows['calculator']['enabled'])
        self.assertEqual(rows['calculator']['count_scope'],'host_lifetime')
        self.assertEqual(rows['native-skills']['recent_uses'],12)
        self.assertEqual(rows['native-skills']['count_scope'],'catalog')
        self.assertEqual(rows['host']['health'],'ready')
        self.assertEqual(rows['memory']['health'],'ready')
        self.assertEqual(rows['memory']['storage_state'],'not_created')
        self.assertEqual(rows['extension-runtime']['health'],'not_implemented')
        self.assertFalse(rows['tts']['installed']);self.assertFalse(rows['tts']['enabled'])
        self.assertEqual(rows['tts']['activity'],'not_integrated')
        self.assertNotIn('sensitive',json.dumps(rows))
        self.assertFalse((self.root/'releases').exists())

    def test_new_stores_are_lazy_and_observation_never_creates_them(self):
        for collector in (self.monitor._memory,self.monitor._knowledge,self.monitor._mcp,self.monitor._skills,self.monitor._persona,self.monitor._continuity):
            row=next(r for r in collector() if r['id'] != 'native-skills')
            self.assertEqual(row['storage_state'],'not_created')
            self.assertEqual(row['record_count'],0)
            self.assertIsNone(row['recent_uses'])
        self.assertEqual(list(self.root.glob('*.db')),[])

    def test_store_observations_are_metadata_only_and_bound_counts(self):
        from jarvis_core.memory import MemoryStore
        from jarvis_core.knowledge import KnowledgeStore
        from jarvis_core.extensions import ExtensionCatalog
        secret='PRIVATE BODY AND ENDPOINT MUST NOT BE OBSERVED'
        with MemoryStore(self.core).connection() as db:
            db.executemany('INSERT INTO facts(id,revision,document,created_at,updated_at,deleted) VALUES(?,1,?,?,?,?)',
                           [(str(i),secret,'2026-01-01','2026-01-02',int(i==1004)) for i in range(1005)])
        with KnowledgeStore(self.core).connection() as db:
            db.execute('INSERT INTO sources(id,revision,path,created_at,updated_at) VALUES(?,1,?,?,?)',
                       ('one',secret,'2026-01-01','2026-01-03'))
        with ExtensionCatalog(self.core).connection() as db:
            db.executemany('INSERT INTO entries VALUES(?,1,?,?,?,?)',
                           [('one','mcp',secret,'2026-01-04',0),('two','skill',secret,'2026-01-05',0),
                            ('deleted','mcp',secret,'2026-01-06',1)])
        rows=[next(r for r in f() if r['id'] != 'native-skills') for f in (self.monitor._memory,self.monitor._knowledge,self.monitor._mcp,self.monitor._skills)]
        self.assertEqual([r['record_count'] for r in rows],[1000,1,1,1])
        self.assertEqual(rows[2]['last_changed'],'2026-01-04')
        self.assertNotIn(secret,json.dumps(rows))
        self.assertTrue(all(r['recent_uses'] is None for r in rows))

    def test_corrupt_or_future_store_does_not_hide_other_modules_or_migrate(self):
        path=self.root/'memory.db';path.write_bytes(b'not sqlite private data')
        with closing(sqlite3.connect(self.root/'project-sources.db')) as db:
            db.execute('PRAGMA user_version=99')
        with patch.object(self.monitor,'_models',return_value=[]):self.monitor._refresh()
        rows={r['id']:r for r in self.monitor.cache['modules']}
        self.assertEqual(rows['memory']['health'],'unknown')
        self.assertEqual(rows['knowledge']['health'],'unknown')
        self.assertEqual(rows['mcp-registration']['health'],'ready')
        self.assertEqual(rows['host']['health'],'ready')
        self.assertNotIn('private data',json.dumps(rows))
        self.assertEqual(path.read_bytes(),b'not sqlite private data')
        with closing(sqlite3.connect(self.root/'project-sources.db')) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],99)

    def test_unwired_store_is_not_reported_enabled(self):
        self.monitor.activity=lambda:{}
        self.assertFalse(self.monitor._memory()[0]['enabled'])
        self.assertEqual(self.monitor._knowledge()[0]['health'],'unavailable')

    def test_usage_is_bounded_and_health_calls_only_fixed_loopback(self):
        with closing(sqlite3.connect(self.root/'model-probes.db')) as db, db:
            db.execute('CREATE TABLE probes(provider TEXT,created_at TEXT)')
            db.executemany('INSERT INTO probes VALUES(?,?)',[('local','2026-10-16')]*1005)
        import httpx
        with patch('jarvis_core.modules.httpx.Client') as client:
            client.return_value.__enter__.return_value.get.return_value=httpx.Response(200)
            rows=self.monitor._models()
            client.return_value.__enter__.return_value.get.assert_called_once_with('http://127.0.0.1:18180/health')
        self.assertEqual(rows[0]['recent_uses'],1000)
        self.assertFalse(rows[1]['installed']);self.assertEqual(rows[1]['activity'],'service_online')

    def test_stopped_host_remains_observable_but_cannot_maintain(self):
        self.core.stopped=True
        self.assertEqual(self.monitor._host()[0]['activity'],'offline')
        with self.assertRaises(RuntimeError):self.monitor.submit({'action':'rollback'})

    def test_input_validation_never_starts_operation(self):
        for payload in ([],{}, {'action':[]},{'action':'restart'}, {'action':'install','archive':'relative.zip'},
                        {'action':'install','archive':'https://example.org/a.zip'},
                        {'action':'health','release_id':'../x'},{'action':'rollback','force':True}):
            with self.subTest(payload=payload),self.assertRaises(ModuleError):self.monitor.submit(payload)
        self.assertIsNone(self.monitor.job)

    def test_maintenance_singleflight_failure_and_restart_unknown(self):
        entered=threading.Event();release=threading.Event()
        def failing(*args,**kwargs):entered.set();release.wait(3);raise ValueError('do not disclose')
        with patch.object(RuntimeSlots,'select',side_effect=failing):
            self.monitor.submit({'action':'rollback'});self.assertTrue(entered.wait(1))
            with self.assertRaises(ModuleError):self.monitor.submit({'action':'rollback'})
            recovered=ModuleMonitor(self.core,lambda:{},releases_root=self.root/'releases')
            self.assertEqual(recovered.jobs[-1]['status'],'UNKNOWN');self.assertIsNone(recovered.job)
            recovered.close();self.core.assert_running();release.set();row=self.wait_job()
        self.assertEqual(row['status'],'FAILED');self.assertNotIn('disclose',json.dumps(row))
        self.assertFalse(self.core.stopped)

    def test_install_health_select_and_tamper_preserve_active(self):
        archive=self.root/'candidate.zip';raw=b'fixture'
        manifest={'schema_version':1,'version':'fixture','files':{'source/hello.txt':{'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}}}
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('source/hello.txt',raw);z.writestr('release.json',json.dumps(manifest))
        self.monitor.submit({'action':'install','archive':str(archive)})
        row=self.wait_job();ident=row['release_id'];self.assertEqual(row['status'],'SUCCEEDED')
        self.monitor.submit({'action':'select','release_id':ident});self.assertEqual(self.wait_job()['status'],'FAILED')
        result=subprocess.CompletedProcess([],0,json.dumps({'status':'passed','version':'fixture'}),'')
        with patch('jarvis_core.releases.subprocess.run',return_value=result):
            self.monitor.submit({'action':'health','release_id':ident});self.assertEqual(self.wait_job()['status'],'SUCCEEDED')
        self.monitor.submit({'action':'select','release_id':ident});self.assertEqual(self.wait_job()['status'],'SUCCEEDED')
        self.assertEqual(self.monitor._releases()['active'],ident)
        (self.root/'releases/slots'/ident/'source/hello.txt').write_text('tampered')
        self.monitor.submit({'action':'health','release_id':ident});self.assertEqual(self.wait_job()['status'],'FAILED')
        self.assertEqual(self.monitor._releases()['active'],ident);self.assertFalse(self.core.stopped)

    def test_record_write_failure_cannot_leave_phantom_running_job(self):
        with patch.object(self.monitor,'_save_jobs',side_effect=OSError('full')):
            with self.assertRaises(OSError):self.monitor.submit({'action':'rollback'})
        self.assertEqual(self.monitor.jobs,[]);self.assertIsNone(self.monitor.job)


class ModuleHTTPTests(unittest.TestCase):
    setUp=test_web.WebTests.setUp
    request=test_web.WebTests.request

    def attach(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.core.data_dir=Path(temp.name)
        monitor=ModuleMonitor(self.core,lambda:{},releases_root=Path(temp.name)/'slots')
        self.server.modules=monitor;self.addCleanup(monitor.close)
        return monitor

    def test_tokens_origin_and_payload_boundaries(self):
        self.attach()
        self.assertEqual(self.request('GET','/api/modules')[0],403)
        self.assertEqual(self.request('POST','/api/modules/refresh',{},headers={'Origin':'http://evil.test'})[0],403)
        self.assertEqual(self.request('POST','/api/modules/refresh',{'extra':True})[0],400)
        self.assertEqual(self.request('POST','/api/modules/maintenance',{'action':[]})[0],400)
        for path in ('/settings','/modules.js'):
            status,_,body=self.request('GET',path);self.assertEqual(status,200);self.assertNotIn(b'__JARVIS_',body)

    def test_slow_observer_and_maintenance_do_not_block_chat(self):
        monitor=self.attach();entered=threading.Event();release=threading.Event()
        self.addCleanup(release.set)
        def slow(*a,**kw):entered.set();release.wait(3);raise ValueError('test')
        def observe():entered.set();release.wait(3)
        with patch.object(monitor,'_refresh',side_effect=observe),patch.object(RuntimeSlots,'select',side_effect=slow):
            start=time.monotonic()
            self.assertEqual(self.request('GET','/api/modules',headers={'X-Jarvis-Nonce':self.server.nonce})[0],200)
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.request('POST','/api/modules/maintenance',{'action':'rollback'})[0],202)
            self.assertEqual(self.request('POST','/api/chat',{'message':'hello'})[0],200)
            self.assertLess(time.monotonic()-start,1)
            release.set()
            end=time.monotonic()+3
            while monitor.job and time.monotonic()<end:time.sleep(.01)
        self.assertEqual(monitor.jobs[-1]['status'],'FAILED')
