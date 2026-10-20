"""Optional TTS lifecycle and a single inference lane independent of chat/tasks."""
from datetime import datetime, timezone
from pathlib import Path
import copy
import hashlib
import json
import os
import secrets
import threading
import time
import uuid

import httpx

from . import policy
from .local_model import OwnedEngine
from .process_memory import process_memory
from .resources import memory_snapshot
from .speech_contract import SpeechError, inference_yaml, validate_synthesis


def now(): return datetime.now(timezone.utc).isoformat()


class SpeechService:
    component_id = 'cosyvoice3'
    worker_relative = 'adapters/speech/cosyvoice3/worker.py'
    api_path = '/api/speech'
    ready_message = 'CosyVoice3 已加载，可合成、克隆和使用情绪指令。'

    def __init__(self, core, *, config_path=None, probe=memory_snapshot, launcher=OwnedEngine):
        self.core = core
        self.config_path = Path(config_path or policy.REPOSITORY_ROOT / ('config/model-profiles/' + self.component_id + '.json'))
        self.cfg = {'threads':4,'model_revision':'unconfigured','max_text_chars':300,'max_reference_seconds':15,'max_output_seconds':60}
        self.config_error = None
        self._reload_profile(strict=False)
        self.data = Path(core.data_dir) / 'speech' / self.component_id
        self.probe, self.launcher = probe, launcher
        self.lock = threading.RLock(); self.closed = False; self.epoch = 0
        self.engine = None; self.worker_pid = None; self.state = 'stopped'; self.job = None; self.last_job = None
        self.token = None; self.endpoint = None; self.health = None; self.uses = 0

    def _reload_profile(self, *, strict):
        try:
            cfg = json.loads(self.config_path.read_text(encoding='utf-8'))
            if cfg['schema_version'] != 1 or cfg['id'] != 'cosyvoice3' or cfg['device'] != 'cpu': raise ValueError()
            for key in ('model_root','environment_root','source_root'):
                if not isinstance(cfg[key],str) or not Path(cfg[key]).is_absolute(): raise ValueError()
            for key, maximum in (('threads',8),('max_text_chars',300),('max_reference_seconds',15),('max_output_seconds',60),
                                 ('request_timeout_seconds',300),('startup_timeout_seconds',240),('minimum_available_memory_gib',64)):
                if type(cfg[key]) is not int or not 1 <= cfg[key] <= maximum: raise ValueError()
            if not cfg['files'] or sum(x['size_bytes'] for x in cfg['files']) > 6_000_000_000: raise ValueError()
            self.cfg = cfg; self.config_error = None
        except (OSError,ValueError,KeyError,TypeError):
            self.config_error = 'CosyVoice3 配置缺失或无效；语音组件未加载，其他模块仍可使用。'
            if strict: raise SpeechError(self.config_error)

    def installed(self):
        if self.config_error: return False
        cfg = self.cfg
        exe = Path(cfg['environment_root']) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        try:
            marker = json.loads((Path(cfg['environment_root']) / 'jarvis-cosyvoice3-ready.json').read_text(encoding='utf-8'))
            expected = hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest()
            return marker.get('profile_sha256') == expected and exe.is_file() and (Path(cfg['source_root']) / 'cosyvoice/cli/cosyvoice.py').is_file() and all(
                (Path(cfg['model_root']) / item['path']).stat().st_size == item['size_bytes'] for item in cfg['files'])
        except (OSError,ValueError): return False

    def snapshot(self):
        with self.lock:
            if not self.engine and not self.job: self._reload_profile(strict=False)
            if self.engine and self.engine.poll() is not None:
                self.engine.stop(); self.engine = None; self.worker_pid = None; self.endpoint = None; self.state = 'failed'
            if self.engine and self.worker_pid and not self.engine.contains(self.worker_pid):
                self.engine.stop(); self.engine = None; self.worker_pid = None; self.endpoint = None; self.state = 'failed'
            pid = (self.worker_pid or self.engine.pid) if self.engine else None
            return {'id': self.component_id, 'installed': self.installed(), 'state': self.state,
                'owned': self.engine is not None, 'pid': pid, 'device': 'cpu', 'threads': self.cfg['threads'],
                'memory': process_memory(pid) if pid else None, 'load': copy.deepcopy(self.health),
                'busy': self.job is not None, 'job': copy.deepcopy(self.job or self.last_job), 'uses': self.uses,
                'model_revision': self.cfg['model_revision'], 'reference_default': '发布方演示参考声音',
                'configuration_notice': self.config_error,
                'limits': {'text_chars': self.cfg['max_text_chars'], 'reference_seconds': self.cfg['max_reference_seconds'],
                           'output_seconds': self.cfg['max_output_seconds']}}

    def _checkpoint(self, epoch):
        self.core.assert_running()
        with self.lock:
            if self.closed or epoch != self.epoch: raise SpeechError('语音操作已停止。')

    def _verify_files(self, epoch):
        cfg = self.cfg
        for item in cfg['files']:
            self._checkpoint(epoch)
            path = policy.safe_path(Path(cfg['model_root']) / item['path'], directory=False)
            if path.stat().st_size != item['size_bytes'] or path.stat().st_nlink != 1:
                raise SpeechError('语音模型文件大小或链接状态不符。')
            h = hashlib.sha256()
            with path.open('rb') as stream:
                while block := stream.read(4 * 1024 * 1024): self._checkpoint(epoch); h.update(block)
            if h.hexdigest() != item['sha256']: raise SpeechError('语音模型摘要不符，未加载。')

    def _prepare(self, epoch):
        self._verify_files(epoch)
        cfg = self.cfg
        for item in cfg.get('source_files', []):
            path = policy.safe_path(Path(cfg['source_root']) / item['path'], directory=False)
            if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                raise SpeechError('语音源码与固定版本不一致，未加载。')
        base = Path(cfg['model_root']); generated = policy.safe_path(base / 'jarvis-inference.yaml', must_exist=False)
        text = inference_yaml((base / 'cosyvoice3.yaml').read_text(encoding='utf-8'))
        if generated.exists() and generated.read_text(encoding='utf-8') != text:
            raise SpeechError('语音推理配置已变化，请运行组件 verify 后重试。')
        if not generated.exists(): generated.write_text(text, encoding='utf-8')

    def _call(self, path, *, payload=None, timeout=1):
        with self.lock: endpoint, token = self.endpoint, self.token
        if not endpoint: raise SpeechError('语音组件尚未就绪。')
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            response = client.request('GET' if payload is None else 'POST', endpoint + path,
                headers={'X-Component-Token': token}, **({'json': payload} if payload is not None else {}))
            response.raise_for_status()
            return response.json()

    def _validate_health(self, health, worker_pid):
        if health.get('pid') != worker_pid or not health.get('ready'):
            raise SpeechError('语音健康回执无效。')

    def _start(self, epoch):
        sample = self.probe(); required = self.cfg['minimum_available_memory_gib'] * 1024 ** 3
        if min(sample['available_bytes'], sample['commit_available_bytes']) < required:
            raise SpeechError('启动语音组件需至少 '+str(self.cfg['minimum_available_memory_gib'])+' GiB 可用内存/提交余量，包含冷加载和前台余量。')
        if not self.installed(): raise SpeechError('语音模型文件或运行环境尚未安装完整。')
        self._prepare(epoch); self._checkpoint(epoch)
        for sub in ('audio', 'references'): policy.safe_path(self.data / sub, must_exist=False).mkdir(parents=True, exist_ok=True)
        ready = policy.safe_path(self.data / ('ready-' + uuid.uuid4().hex + '.json'), must_exist=False)
        launch_config = policy.safe_path(ready.with_name('profile-' + ready.name[6:]), must_exist=False)
        launch_config.write_text(json.dumps(self.cfg), encoding='utf-8')
        exe = Path(self.cfg['environment_root']) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        argv = [str(policy.safe_path(exe, directory=False)), str(policy.REPOSITORY_ROOT / self.worker_relative),
                '--config', str(launch_config), '--data-dir', str(self.data), '--ready-file', str(ready)]
        try:
            with self.lock:
                self._checkpoint(epoch); self.token = secrets.token_urlsafe(32)
                self.worker_pid = None; self.health = None
                # URL-safe random tokens may begin with '-'; bind the value so
                # argparse cannot mistake a fresh token for another option.
                self.engine = self.launcher(argv + ['--token=' + self.token])
            deadline = time.monotonic() + self.cfg['startup_timeout_seconds']
            while time.monotonic() < deadline:
                self._checkpoint(epoch)
                with self.lock:
                    if not self.engine or self.engine.poll() is not None: raise SpeechError('语音进程加载失败，详情见本机 worker.log。')
                    pid = self.engine.pid
                if ready.exists():
                    if ready.stat().st_size > 1024: raise SpeechError('语音就绪回执无效。')
                    value = json.loads(ready.read_text(encoding='utf-8'))
                    worker_pid = value.get('pid')
                    if not self.engine.contains(worker_pid) or type(value.get('port')) is not int or not 1 <= value['port'] <= 65535:
                        raise SpeechError('语音就绪回执不匹配。')
                    with self.lock:
                        self.worker_pid = worker_pid; self.endpoint = 'http://127.0.0.1:' + str(value['port'])
                    health = self._call('/health')
                    self._validate_health(health, worker_pid)
                    with self.lock: self._checkpoint(epoch); self.health = health; self.state = 'ready'
                    return {'message': self.ready_message, 'load': health}
                time.sleep(.2)
            raise SpeechError('语音加载超时，已回收本次组件进程。')
        finally:
            if ready.exists(): policy.safe_path(ready, directory=False).unlink()
            if launch_config.exists(): policy.safe_path(launch_config, directory=False).unlink()

    def parse_synthesis(self, payload):
        return validate_synthesis(payload)

    def default_reference(self):
        return Path(self.cfg['source_root']) / 'asset/zero_shot_prompt.wav'

    def synthesis_request(self, parsed, row):
        reference = self.default_reference(); temporary = None
        if parsed['reference_data'] is not None:
            temporary = policy.safe_path(self.data / 'references' / (row['id'] + '.wav'), must_exist=False)
            with temporary.open('xb') as stream: stream.write(parsed['reference_data'])
            reference = temporary
        request = {k: parsed[k] for k in ('text', 'mode', 'emotion', 'reference_text')}
        request.update(id=row['id'], reference_path=str(reference))
        return request, temporary

    def submit(self, payload):
        self.core.assert_running()
        if not isinstance(payload, dict): raise SpeechError('语音请求无效。')
        action = payload.get('action')
        if action == 'stop':
            if set(payload) != {'action'}: raise SpeechError('停止语音只接受 action。')
            self.stop(); return self.snapshot()
        parsed = self.parse_synthesis(payload) if action == 'synthesize' else None
        if action not in {'start', 'synthesize'} or action == 'start' and set(payload) != {'action'}:
            raise SpeechError('未知语音操作。')
        with self.lock:
            if self.closed: raise SpeechError('语音服务正在退出。')
            if self.job: raise SpeechError('语音组件已有操作在执行；聊天与后台任务可以继续。')
            if action == 'start' and self.engine: return self.snapshot()
            if action == 'start': self._reload_profile(strict=True)
            if action == 'synthesize' and self.state != 'ready': raise SpeechError('请先加载语音模型。')
            row = {'id': uuid.uuid4().hex, 'action': action, 'status': 'RUNNING', 'started_at': now()}
            self.job = row; epoch = self.epoch; self.state = 'loading' if action == 'start' else 'busy'
            threading.Thread(target=self._run, args=(row, epoch, parsed), name='jarvis-' + self.component_id, daemon=True).start()
        return self.snapshot()

    def _run(self, row, epoch, parsed):
        temporary = None
        from .runtime_admission import coordinator
        lease = None
        finished = threading.Event()
        def watch_control():
            while not finished.wait(.25):
                try: self._checkpoint(epoch)
                except Exception:
                    with self.lock:
                        if epoch == self.epoch: self.stop()
                    return
        threading.Thread(target=watch_control, name='jarvis-speech-control', daemon=True).start()
        try:
            lease = coordinator(self.core).acquire('tts', 1024, owner=row['id'])
            if row['action'] == 'start': result = self._start(epoch)
            else:
                self._checkpoint(epoch)
                request, temporary = self.synthesis_request(parsed, row)
                result = self._call('/synthesize', payload=request, timeout=self.cfg['request_timeout_seconds'])
                self._checkpoint(epoch)
                result.update(audio_url=self.api_path + '/audio/' + row['id'])
            with self.lock:
                self._checkpoint(epoch); self.state = 'ready'
                if row['action'] == 'synthesize': self.uses += 1
                row.update(status='SUCCEEDED', finished_at=now(), result=result)
        except Exception as exc:
            with self.lock:
                if epoch == self.epoch:
                    if self.engine: self.engine.stop(); self.engine = None
                    self.endpoint = None; self.worker_pid = None; self.state = 'failed'
                    row.update(status='FAILED', finished_at=now(), message=str(exc) if isinstance(exc, SpeechError) else
                        '语音操作失败或超时，本次语音进程已回收；聊天服务继续运行。')
        finally:
            if lease is not None: coordinator(self.core).release(lease)
            finished.set()
            if temporary and temporary.exists():
                try: temporary.unlink()
                except OSError: row['cleanup_notice'] = '临时参考文件未能移除，请检查本机 references 目录。'
            with self.lock:
                if epoch == self.epoch:
                    self.last_job = copy.deepcopy(row); self.job = None

    def stop(self):
        with self.lock:
            self.epoch += 1
            if self.job:
                self.job.update(status='CANCELLED', finished_at=now(), message='语音操作已停止。')
                self.last_job = copy.deepcopy(self.job); self.job = None
            if self.engine: self.engine.stop(); self.engine = None
            self.endpoint = self.token = self.worker_pid = None; self.state = 'stopped'

    def close(self):
        with self.lock: self.closed = True
        self.stop()

    def audio(self, ident):
        if len(ident) != 32 or any(c not in '0123456789abcdef' for c in ident): raise SpeechError('音频标识无效。')
        path = policy.safe_path(self.data / 'audio' / (ident + '.wav'), directory=False)
        if path.stat().st_size > 3_000_044: raise SpeechError('音频文件超过组件上限。')
        return path.read_bytes()
