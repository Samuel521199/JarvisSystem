"""Actual Windows Worker boundary checks using only temporary synthetic data."""
import copy
import ctypes
from ctypes import wintypes
import json
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime/node-host'))
from jarvis_core import worker, policy
from jarvis_core.service import CoreService
from jarvis_worker.windows import run, WorkerError, require_acl_volume


def process_alive(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(handle, 0) == 258
    finally:
        kernel.CloseHandle(handle)


@unittest.skipUnless(os.name == 'nt', 'Native Windows Worker backend')
class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime, cls.bundle = worker.verify_bundle()
        parent = worker.workspace() / 'worker-staging'
        parent.mkdir(parents=True, exist_ok=True)
        cls.parent = parent

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='probe-', dir=self.parent)
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.stage = self.base / 'stage'
        self.stage.mkdir()

    def launch(self, code, **kwargs):
        (self.stage / 'worker.py').write_text(code, encoding='utf-8')
        return run(self.runtime, self.stage, **kwargs)

    def test_real_denials_files_network_child_and_secret_environment(self):
        outside = self.base / 'credential-canary'
        outside.write_text('synthetic secret')
        (self.stage / 'input.json').write_text('{}')
        with socket.socket() as listener, tempfile.TemporaryDirectory(prefix='worker-canary-', dir=ROOT) as extra:
            extra_file = Path(extra) / 'source-canary.txt'
            extra_file.write_text('synthetic source')
            listener.bind(('127.0.0.1', 0)); listener.listen(1)
            code = """import os,json,socket,subprocess,sys
result={}
def probe(name,fn):
    try:fn(); result[name]={'allowed':True}
    except OSError as e:result[name]={'allowed':False,'errno':e.errno,'winerror':getattr(e,'winerror',None)}
for name,path in PATHS.items():
    probe(name+'_read',lambda:open(path).read())
    probe(name+'_write',lambda:open(path,'w').write('bad'))
probe('input_write',lambda:open('input.json','w').write('bad'))
probe('network',lambda:socket.create_connection(('127.0.0.1',PORT),1))
probe('child',lambda:subprocess.run([sys.executable,'-c','pass'],timeout=1))
result['secret_environment']=os.environ.get('JARVIS_TEST_SECRET')
os.write(1,json.dumps(result).encode())
""".replace('PATHS', repr({'private':str(outside), 'source_volume':str(extra_file)})).replace('PORT', str(listener.getsockname()[1]))
            with patch.dict(os.environ, {'JARVIS_TEST_SECRET':'synthetic'}):
                result = self.launch(code)
            self.assertEqual(result['exit_code'], 0, result['stderr'])
            reply = json.loads(result['stdout'])
            self.assertIsNone(reply.pop('secret_environment'))
            self.assertTrue(all(not value['allowed'] for value in reply.values()), reply)
            self.assertEqual(reply['network']['winerror'], 10013)
            self.assertEqual(reply['child']['winerror'], 367)
            self.assertEqual(outside.read_text(), 'synthetic secret')
            self.assertEqual(extra_file.read_text(), 'synthetic source')
            self.assertTrue(result['evidence']['lpac'])
            self.assertEqual(result['evidence']['capabilities'], ['registryRead'])

    def test_timeout_and_output_quota_terminate_job(self):
        for code, options, expected in (
            ('import time; time.sleep(30)', {'seconds':.5}, 'worker_timeout'),
            ("import os; os.write(1,b'x'*65536)", {'output_limit':1024}, 'worker_output_limit'),
        ):
            with self.subTest(expected=expected), self.assertRaises(WorkerError) as error:
                self.launch(code, **options)
            self.assertEqual(error.exception.code, expected)

    def test_memory_quota_is_enforced(self):
        result = self.launch("import os\ntry: x=bytearray(256*1024*1024)\nexcept MemoryError: os.write(1,b'limited')", memory_limit=64*1024*1024)
        self.assertEqual(result['stdout'], b'limited')
        self.assertEqual(result['exit_code'], 0)
        self.assertLessEqual(result['evidence']['peak_process_memory_bytes'], 64*1024*1024)

    def test_cpu_quota_terminates_busy_worker(self):
        start=time.monotonic()
        with self.assertRaises(WorkerError) as error:
            self.launch('while True: pass', seconds=8)
        self.assertEqual(error.exception.code,'worker_cpu_limit')
        self.assertLess(time.monotonic()-start,8)

    def test_parent_crash_kills_worker(self):
        # PID is sent via the only permitted output pipe. The parent exits
        # without finally blocks, so termination depends on the OS Job object.
        (self.stage / 'worker.py').write_text('import os,time;os.write(1,str(os.getpid()).encode());time.sleep(30)')
        pid_file = self.base / 'pid.txt'
        script = """import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from jarvis_worker.windows import Windows,run
original=Windows.__init__
def initialize(self):
 original(self)
 original_profile=self.create_profile
 def create_profile(name,*args):
  Path(sys.argv[4]+'.profile').write_text(name)
  return original_profile(name,*args)
 self.create_profile=create_profile
 original_read=self.read
 def read(handle,buffer,size,count,overlap):
  result=original_read(handle,buffer,size,count,overlap)
  if result:
   Path(sys.argv[4]).write_bytes(buffer.raw[:count._obj.value]); os._exit(77)
  return result
 self.read=read
Windows.__init__=initialize
run(Path(sys.argv[2]),Path(sys.argv[3]))
"""
        try:
            parent = subprocess.run([sys.executable, '-B', '-c', script, str(ROOT/'runtime/worker-host'),
                                     str(self.runtime), str(self.stage), str(pid_file)], capture_output=True, timeout=10)
            self.assertEqual(parent.returncode, 77, parent.stderr)
            pid = int(pid_file.read_text())
            until = time.monotonic()+3
            while process_alive(pid) and time.monotonic()<until:
                time.sleep(.02)
            self.assertFalse(process_alive(pid), 'Worker survived host crash')
        finally:
            profile_file=Path(str(pid_file)+'.profile')
            if profile_file.exists():
                from jarvis_worker.windows import Windows
                self.assertEqual(Windows().delete_profile(profile_file.read_text()),0)

    def test_cancel_and_stop_during_real_worker_prevent_artifact(self):
        for operation in ('cancel','stop'):
            with self.subTest(operation=operation):
                base = self.base / operation; base.mkdir(); source=base/'input';source.mkdir()
                service=CoreService(base/'data');service.initialize(source)
                entered=threading.Event()
                original=worker.run
                def slow(runtime, stage, **kwargs):
                    (stage/'worker.py').write_text('import time;time.sleep(30)')
                    checkpoint=kwargs['checkpoint']
                    count=0
                    def check():
                        nonlocal count
                        count+=1
                        if count>=4:entered.set()
                        checkpoint()
                    return original(runtime,stage,checkpoint=check)
                results=[]
                prepared=service.prepare_inventory()
                with patch.object(worker,'run',slow):
                    thread=threading.Thread(target=lambda:results.append(service.run(prepared['action']['action_id'])))
                    thread.start();self.assertTrue(entered.wait(5))
                    if operation=='stop':service.stop('synthetic worker stop')
                    else:service.cancel(prepared['task']['task_id'])
                    thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(results[0]['action']['status'],'CANCELLED')
                self.assertFalse(list((base/'data/artifacts').iterdir()))

    def test_invalid_bundle_fails_without_unrestricted_fallback(self):
        source=self.base/'input';source.mkdir();service=CoreService(self.base/'data');service.initialize(source)
        with patch.object(worker,'verify_bundle',side_effect=WorkerError('worker_bundle_invalid','synthetic digest mismatch')), \
             patch.object(worker,'run',side_effect=AssertionError('Must not launch')):
            result=service.inventory()
        self.assertEqual(result['action']['error']['code'],'worker_bundle_invalid')
        self.assertEqual(result['action']['status'],'FAILED')
        self.assertIsNone(result['artifact'])

    def test_bundle_digest_and_file_allowlist_are_actually_checked(self):
        root=self.base/'fake-source';(root/'config').mkdir(parents=True)
        name='worker-python-synthetic'
        bundle=self.base/'worker-runtimes'/name;bundle.mkdir(parents=True)
        files={name:b'synthetic' for name in ('python.exe','python313.dll','python313._pth','stdlib.zip')}
        for name,content in files.items():(bundle/name).write_bytes(content)
        manifest=json.dumps({'files':{name:hashlib.sha256(value).hexdigest() for name,value in files.items()}}).encode()
        (bundle/'bundle.json').write_bytes(manifest)
        profile={'schema_version':1,'backend':'windows-lpac-job','runtime_directory':bundle.name,
                 'manifest_sha256':hashlib.sha256(manifest).hexdigest()}
        (root/'config/worker-profile.json').write_text(json.dumps(profile))
        with patch.object(policy,'REPOSITORY_ROOT',root),patch.object(worker,'workspace',return_value=self.base):
            self.assertEqual(worker.verify_bundle()[0],bundle)
            (bundle/'python.exe').write_bytes(b'changed')
            with self.assertRaises(WorkerError):worker.verify_bundle()
            (bundle/'python.exe').write_bytes(b'synthetic')
            (bundle/'unapproved.pyd').write_bytes(b'extra')
            with self.assertRaises(WorkerError):worker.verify_bundle()

    def test_effective_identity_verification_failure_cannot_resume_worker(self):
        from jarvis_worker.windows import Windows
        with patch.object(Windows,'verify_token',side_effect=WorkerError('worker_isolation_failed','synthetic token mismatch')):
            with self.assertRaises(WorkerError):
                self.launch("import os;os.write(1,b'should never run')")


class WorkerProtocolTests(unittest.TestCase):
    def test_reply_binding_and_metadata_cannot_be_changed(self):
        binding={'nonce':'one','security_epoch':1,'task_id':'task_one'}
        inventory={'total_files':0,'total_bytes':0,'files':[]}
        valid={'binding':binding,'inventory':inventory}
        self.assertEqual(worker.validate_reply(json.dumps(valid).encode(),binding,inventory),inventory)
        candidates=[]
        for key,value in (('nonce','old'),('security_epoch',True),('task_id','task_other')):
            candidate=copy.deepcopy(valid);candidate['binding'][key]=value;candidates.append(candidate)
        candidate=copy.deepcopy(valid);candidate['inventory']['files']=[{'path':'../escape'}];candidates.append(candidate)
        candidate=copy.deepcopy(valid);candidate['command']='shell';candidates.append(candidate)
        for candidate in candidates:
            with self.subTest(candidate=candidate), self.assertRaises(WorkerError):
                worker.validate_reply(json.dumps(candidate).encode(),binding,inventory)
        for raw in (b'not json',b'\xff',b'x'*(policy.MAX_OUTPUT_BYTES+1),b'['*2000+b']'*2000):
            with self.assertRaises(WorkerError):worker.validate_reply(raw,binding,inventory)
        raw=json.dumps(valid).replace('"nonce": "one"','"nonce":"bad","nonce":"one"').encode()
        with self.assertRaises(WorkerError):worker.validate_reply(raw,binding,inventory)


if __name__ == '__main__':
    unittest.main()
