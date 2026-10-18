"""Owned model lifecycle must remain explicit, bounded and independent."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch,Mock
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core.local_model import LocalModel,LocalModelError,OwnedEngine,prepare,command
from jarvis_core.modules import ModuleMonitor,ModuleError
from tests.test_web import FakeCore


class LocalModelTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.core=FakeCore();self.core.data_dir=self.root/'data';self.core.data_dir.mkdir()
        self.runtime=LocalModel(self.core,model_root=self.root/'models',probe=lambda:{'available_bytes':8*1024**3,'commit_available_bytes':8*1024**3})
        self.addCleanup(self.runtime.close)

    def test_memory_and_external_port_reject_before_preparing(self):
        with patch.object(self.runtime,'port_in_use',return_value=True),patch('jarvis_core.local_model.prepare') as load:
            with self.assertRaises(LocalModelError):self.runtime.start()
            load.assert_not_called()
        with patch.object(self.runtime,'port_in_use',return_value=False),patch('jarvis_core.local_model.prepare') as load:
            self.runtime.probe=lambda:{'available_bytes':1024,'commit_available_bytes':1024}
            with self.assertRaises(LocalModelError):self.runtime.start()
            load.assert_not_called()
        self.assertFalse(self.runtime.snapshot()['owned'])

    def test_success_idempotence_busy_stop_and_own_cleanup(self):
        with patch.object(self.runtime,'port_in_use',return_value=False),patch('jarvis_core.local_model.prepare',return_value=(self.root/'engine.exe',self.root/'m.gguf')),patch('jarvis_core.local_model.OwnedEngine') as engine,patch('jarvis_core.local_model.httpx.Client') as client:
            engine.return_value.pid=1;engine.return_value.poll.return_value=None
            client.return_value.__enter__.return_value.get.return_value.status_code=200
            self.runtime.start();self.runtime.start();engine.assert_called_once()
            self.assertEqual(self.runtime.snapshot()['state'],'running')
            self.runtime.activity=lambda:{'chat':1}
            with self.assertRaises(LocalModelError):self.runtime.stop()
            engine.return_value.stop.assert_not_called()
            self.runtime.activity=lambda:{};self.runtime.stop();engine.return_value.stop.assert_called_once()
            self.assertFalse(self.runtime.snapshot()['owned'])

    def test_close_during_prepare_prevents_late_launch(self):
        entered=threading.Event();release=threading.Event();errors=[]
        def load(*a,**kw):entered.set();release.wait(3);kw['checkpoint']();return self.root/'engine',self.root/'model'
        def start():
            try:self.runtime.start()
            except LocalModelError as e:errors.append(str(e))
        with patch.object(self.runtime,'port_in_use',return_value=False),patch('jarvis_core.local_model.prepare',side_effect=load),patch('jarvis_core.local_model.OwnedEngine') as engine:
            t=threading.Thread(target=start);t.start();self.assertTrue(entered.wait(1))
            begin=time.monotonic();self.runtime.close();self.assertLess(time.monotonic()-begin,.3)
            release.set();t.join(3);engine.assert_not_called();self.assertTrue(errors)

    def test_failed_engine_is_observed_without_restart(self):
        engine=Mock();engine.poll.return_value=1;self.runtime.engine=engine
        self.assertEqual(self.runtime.snapshot()['state'],'failed');engine.stop.assert_called_once()
        self.assertFalse(self.runtime.snapshot()['owned'])

    def test_fixed_command_ignores_environment_overrides(self):
        argv=command(Path('engine.exe'),Path('model.gguf'))
        self.assertIn('--offline',argv);self.assertIn('127.0.0.1',argv)
        self.assertEqual(argv[argv.index('-t')+1],'4');self.assertEqual(argv[argv.index('-ngl')+1],'0')
        self.assertEqual(argv[argv.index('-np')+1],'1');self.assertEqual(argv[argv.index('-n')+1],'256')

    def fixture(self,member='llama-server.exe'):
        base=self.root/'models';base.mkdir();(base/'model.gguf').write_bytes(b'fixture')
        with zipfile.ZipFile(base/'runtime.zip','w') as z:z.writestr(member,b'engine fixture')
        entries=[]
        for path,ident,component in [('model.gguf','model','qwen3-0.6b'),('runtime.zip','llamacpp-win-cpu','llamacpp')]:
            raw=(base/path).read_bytes();entries.append({'path':path,'id':ident,'component':component,'revision':'fixture','size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
        manifest=self.root/'config/model-profiles/local-candidates.json';manifest.parent.mkdir(parents=True);manifest.write_text(json.dumps({'files':entries}))
        return base

    def test_pinned_prepare_and_tampered_cache_never_overwrites(self):
        base=self.fixture()
        with patch('jarvis_core.local_model.policy.REPOSITORY_ROOT',self.root):
            exe,model=prepare(base);self.assertEqual(model.read_bytes(),b'fixture')
            self.assertEqual(prepare(base)[0],exe)
            exe.write_bytes(b'tampered')
            with self.assertRaises(LocalModelError):prepare(base)
            self.assertEqual(exe.read_bytes(),b'tampered')

    def test_bad_model_hash_and_archive_traversal_rejected(self):
        base=self.fixture('../outside.exe')
        with patch('jarvis_core.local_model.policy.REPOSITORY_ROOT',self.root):
            with self.assertRaises(LocalModelError):prepare(base)
            self.assertFalse((base/'runtimes/outside.exe').exists())
            (base/'model.gguf').write_bytes(b'changed')
            with self.assertRaises(LocalModelError):prepare(base)

    def test_module_lane_controls_are_async_strict_and_close_owned_model(self):
        monitor=ModuleMonitor(self.core,lambda:{},model_root=self.root/'models');self.addCleanup(monitor.close)
        entered=threading.Event();release=threading.Event()
        def start():entered.set();release.wait(3);return 'local ready'
        with patch.object(monitor.local_model,'start',side_effect=start),patch.object(monitor.local_model,'stop',return_value='stopped') as stop:
            monitor.submit({'action':'local-start'});self.assertTrue(entered.wait(1))
            self.assertTrue(monitor.snapshot()['maintenance_busy'])
            with self.assertRaises(ModuleError):monitor.submit({'action':'local-start','model':'anything'})
            with self.assertRaises(ModuleError):monitor.submit({'action':'local-stop'})
            release.set()
            for _ in range(100):
                if not monitor.job:break
                time.sleep(.01)
            self.assertEqual(monitor.jobs[-1]['message'],'local ready')
            monitor.submit({'action':'local-stop'})
            for _ in range(100):
                if not monitor.job:break
                time.sleep(.01)
            stop.assert_called_once();self.assertEqual(monitor.jobs[-1]['status'],'SUCCEEDED')
        self.assertFalse(self.core.stopped)

    @unittest.skipUnless(os.name=='nt','Native Windows lifecycle')
    def test_native_job_stops_only_its_child_and_strips_secrets(self):
        target=self.root/'env.json'
        script=('import os,json,time,sys;from pathlib import Path;'
                'target=Path(sys.argv[1]);temporary=target.with_suffix(".tmp");'
                'temporary.write_text(json.dumps(dict(os.environ)));temporary.replace(target);'
                'time.sleep(30)')
        with patch.dict(os.environ,{'JARVIS_SECRET_FIXTURE':'must not inherit','LLAMA_ARG_HOST':'0.0.0.0'}):
            engine=OwnedEngine([sys.executable,'-I','-B','-c',script,str(target)])
        try:
            for _ in range(100):
                if target.exists():break
                time.sleep(.01)
            env=json.loads(target.read_text());self.assertNotIn('JARVIS_SECRET_FIXTURE',env);self.assertNotIn('LLAMA_ARG_HOST',env)
            self.assertIsNone(engine.poll())
        finally:engine.stop()
        self.assertIsNotNone(engine.poll())


if __name__=='__main__':unittest.main()
