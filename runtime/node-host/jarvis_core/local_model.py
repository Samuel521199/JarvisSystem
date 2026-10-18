"""Explicit, owned CPU inference lifecycle. No downloads, cloud calls or watchdog.

Only the pinned local model/archive and fixed launch profile are accepted.
The Windows Job is attached atomically at process creation; it is a lifetime
boundary, not an inference security sandbox or an outbound firewall.
"""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import socket
import subprocess
import threading
import time
import zipfile

import httpx

from . import policy
from .resources import memory_snapshot, MIB


class LocalModelError(ValueError):
    pass


def prepare(base, *, checkpoint=lambda: None):
    base=Path(base)
    manifest=json.loads((policy.REPOSITORY_ROOT/'config/model-profiles/local-candidates.json').read_text(encoding='utf-8'))
    entries=manifest['files']
    model=next(x for x in entries if x['component']=='qwen3-0.6b' and x['path'].endswith('.gguf'))
    archive=next(x for x in entries if x['id']=='llamacpp-win-cpu')
    def target(relative, **kwargs):
        name=PurePosixPath(relative)
        if name.is_absolute() or '..' in name.parts or '\\' in relative or ':' in relative:
            raise LocalModelError('本地组件路径无效。')
        return policy.safe_path(base/Path(name),**kwargs)
    for item in (model,archive):
        path=target(item['path'],directory=False)
        if path.stat().st_size!=item['size_bytes'] or path.stat().st_nlink!=1:
            raise LocalModelError('本地模型或运行包大小不符；未下载或启动。')
        digest=hashlib.sha256()
        with path.open('rb') as source:
            while block:=source.read(1024*1024):checkpoint();digest.update(block)
        if digest.hexdigest()!=item['sha256']:
            raise LocalModelError('本地模型或运行包摘要不符；未下载或启动。')
    destination=target('runtimes/llamacpp-'+archive['revision'],must_exist=False,directory=True)
    destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target(archive['path'],directory=False)) as source:
        if len(source.infolist())>1000 or sum(x.file_size for x in source.infolist())>300_000_000:
            raise LocalModelError('本地运行包超过展开上限。')
        for item in source.infolist():
            checkpoint()
            if (item.external_attr>>16)&0o170000==0o120000:
                raise LocalModelError('本地运行包不能包含链接。')
            relative=destination.relative_to(base).as_posix()+'/'+item.filename.replace('\\','/')
            path=target(relative,must_exist=False)
            if item.is_dir():path.mkdir(parents=True,exist_ok=True);continue
            content=source.read(item)
            if path.exists():
                if path.stat().st_nlink!=1 or hashlib.sha256(path.read_bytes()).digest()!=hashlib.sha256(content).digest():
                    raise LocalModelError('缓存运行组件已变化；未覆盖或启动。')
            else:
                path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('xb') as stream:stream.write(content)
    executables=list(destination.rglob('llama-server.exe'))
    if len(executables)!=1:raise LocalModelError('本地运行包缺少唯一推理入口。')
    checkpoint()
    return executables[0],target(model['path'],directory=False)


def command(executable, model):
    return [str(executable),'-m',str(model),'--host','127.0.0.1','--port','18180',
            '-c','2048','-t','4','-ngl','0','-np','1','--jinja','-n','256',
            '--offline','--alias','qwen3-0.6b','--poll','0','--poll-batch','0']


class OwnedEngine:
    def __init__(self, argv):
        if os.name!='nt':raise LocalModelError('页面启动目前仅验证 Windows。')
        from . import worker  # Registers the existing native Win32 structures.
        from jarvis_worker.windows import Windows,JobLimits,StartupInfoEx,ProcessInformation,SIZE,P
        self.api=Windows();self.job=self.process=None
        attributes=None;initialized=False
        try:
            self.job=self.api.check(self.api.create_job(None,None),'Create model lifetime Job')
            limits=JobLimits();limits.basic.flags=0x2000
            self.api.check(self.api.set_job(self.job,9,C.byref(limits),C.sizeof(limits)),'Set model lifetime Job')
            size=SIZE();self.api.init_attrs(None,1,0,C.byref(size));attributes=C.create_string_buffer(size.value)
            self.api.check(self.api.init_attrs(attributes,1,0,C.byref(size)),'Initialize model attributes');initialized=True
            jobs=(P*1)(self.job)
            self.api.check(self.api.update_attr(attributes,0,0x2000D,jobs,C.sizeof(jobs),None,None),'Attach model Job before launch')
            startup=StartupInfoEx();startup.startup.cb=C.sizeof(startup);startup.attributes=C.cast(attributes,P)
            process=ProcessInformation()
            # Exclude credentials, proxy variables and LLAMA_ARG_* overrides.
            env={k:os.environ[k] for k in ('SystemRoot','WINDIR','TEMP','TMP','USERPROFILE') if k in os.environ}
            block=C.create_unicode_buffer('\0'.join(k+'='+v for k,v in sorted(env.items()))+'\0\0')
            self.api.check(self.api.create(argv[0],C.create_unicode_buffer(subprocess.list2cmdline(argv)),None,None,
                False,0x80000|0x8000000|0x400,block,str(Path(argv[0]).parent),C.byref(startup),C.byref(process)),
                'Start owned local model')
            self.process=process.process;self.pid=process.pid;self.api.close(process.thread)
        except Exception:self.stop();raise
        finally:
            if initialized:self.api.delete_attrs(attributes)

    def poll(self):
        return None if self.process and self.api.wait(self.process,0)==0x102 else 1

    def contains(self, pid):
        """Include Windows venv redirector children, verified against our lifetime Job."""
        if not self.job or type(pid) is not int or pid < 1: return False
        from ctypes import wintypes as W
        kernel = C.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype = W.HANDLE
        kernel.IsProcessInJob.argtypes = [W.HANDLE,W.HANDLE,C.POINTER(W.BOOL)];kernel.IsProcessInJob.restype = W.BOOL
        kernel.CloseHandle.argtypes = [W.HANDLE]
        handle = kernel.OpenProcess(0x1000,False,pid)
        if not handle: return False
        try:
            member = W.BOOL()
            return bool(kernel.IsProcessInJob(handle,self.job,C.byref(member)) and member.value)
        finally:kernel.CloseHandle(handle)

    def stop(self):
        if self.job:self.api.kill_job(self.job,1);self.api.close(self.job);self.job=None
        if self.process:self.api.wait(self.process,3000);self.api.close(self.process);self.process=None


class LocalModel:
    def __init__(self,core,*,model_root=None,activity=lambda:{},probe=memory_snapshot):
        self.core,self.activity,self.probe=core,activity,probe
        self.model_root=Path(model_root) if model_root else None
        self.lock=threading.Lock();self.closed=threading.Event();self.engine=None;self.state='stopped'

    def snapshot(self):
        with self.lock:
            if self.engine and self.engine.poll() is not None:
                self.engine.stop();self.engine=None;self.state='failed'
            return {'owned':self.engine is not None,'state':self.state,'pid':self.engine.pid if self.engine else None}

    def _checkpoint(self):
        if self.closed.is_set():raise LocalModelError('实例正在退出，未继续启动本地模型。')
        self.core.assert_running()

    @staticmethod
    def port_in_use():
        with socket.socket() as sock:
            sock.settimeout(.3)
            return sock.connect_ex(('127.0.0.1',18180))==0

    def start(self):
        self._checkpoint()
        if self.snapshot()['state']=='running':return '本实例的本地模型已在线，未重复启动。'
        if self.port_in_use():raise LocalModelError('18180 已被其他服务占用；未接管或停止外部进程。')
        self._memory_ready()
        with self.lock:
            if self.state=='starting':raise LocalModelError('本地模型已在启动中，未重复创建进程。')
            self._checkpoint();self.state='starting'
        try:
            root=self.model_root
            if root is None:
                manifest=json.loads((policy.REPOSITORY_ROOT/'config/model-profiles/local-candidates.json').read_text(encoding='utf-8'));root=Path(manifest['default_root'])
            executable,model=prepare(root,checkpoint=self._checkpoint)
            self._checkpoint()
            self._memory_ready()
            if self.port_in_use():raise LocalModelError('启动期间端口已被占用，未启动或接管外部服务。')
            with self.lock:
                self._checkpoint();self.engine=OwnedEngine(command(executable,model))
            with httpx.Client(timeout=.8,trust_env=False,follow_redirects=False) as client:
                deadline=time.monotonic()+45
                while time.monotonic()<deadline:
                    self._checkpoint()
                    if not self.snapshot()['owned']:raise LocalModelError('本地推理进程已退出；未自动重启。')
                    try:
                        if client.get('http://127.0.0.1:18180/health').status_code==200:
                            with self.lock:self._checkpoint();self.state='running'
                            return '本地 Qwen3 0.6B 已启动，可选择本地模型聊天或执行固定目录报告。'
                    except httpx.HTTPError:pass
                    time.sleep(.2)
            raise LocalModelError('本地模型就绪超时，已回收本次进程。')
        except Exception:
            self._stop('failed');raise

    def _memory_ready(self):
        sample=self.probe();required=(1024+1536)*MIB
        if min(sample['available_bytes'],sample['commit_available_bytes'])<required:
            raise LocalModelError('内存不足：本地模型启动估算需 1,536 MiB，并保留 1,024 MiB 前台余量。')

    def _stop(self,state='stopped'):
        with self.lock:
            if self.engine:self.engine.stop();self.engine=None
            self.state=state

    def stop(self):
        activity=self.activity()
        if activity.get('chat') or activity.get('tasks'):
            raise LocalModelError('仍有聊天或后台任务在执行；请结束后再停止本地模型。')
        self._stop();return '已停止本实例启动的本地模型，聊天服务继续待命；外部服务未被停止。'

    def close(self):
        self.closed.set();self._stop()
