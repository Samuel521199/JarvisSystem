"""Ephemeral, one-at-a-time local ASR. No microphone access or audio files."""
import base64
import binascii
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from . import policy
from .dialogue_process import ProcessJob
from .process_memory import process_memory
from .resources import memory_snapshot
from .speech_contract import SpeechError

MAX_SECONDS = 20
MAX_PCM = 16000 * 2 * MAX_SECONDS
MEMORY_LIMIT = 1536 * 1024**2
LANGUAGES = {'auto', 'zh', 'en', 'ja', 'ko', 'yue'}


def validate(payload):
    if not isinstance(payload, dict):
        raise SpeechError('语音输入必须是对象。')
    action, ident = payload.get('action'), payload.get('id')
    if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident):
        raise SpeechError('语音输入编号无效。')
    fields = {'transcribe': {'action', 'id', 'pcm', 'language'},
              'cancel': {'action', 'id'}, 'forget': {'action', 'id'}}
    if not isinstance(action, str) or action not in fields or set(payload) != fields[action]:
        raise SpeechError('语音输入字段无效。')
    if action != 'transcribe':
        return action, ident, None
    language, encoded = payload['language'], payload['pcm']
    if not isinstance(language, str) or language not in LANGUAGES:
        raise SpeechError('识别语言无效。')
    if not isinstance(encoded, str) or len(encoded) > (MAX_PCM + 2)//3 * 4:
        raise SpeechError('每次录音最多 20 秒。')
    try:
        pcm = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise SpeechError('录音编码无效。') from None
    if not 6400 <= len(pcm) <= MAX_PCM or len(pcm) % 2:
        raise SpeechError('录音须为 0.2—20 秒、16 kHz 单声道 PCM16。')
    return action, ident, pcm


class SpeechInput:
    TTL = 300

    def __init__(self, core, *, model_root=None, runner=None):
        self.core = core
        self.model_root = model_root
        self.runner = runner or self._recognize
        self.lock = threading.RLock()
        self.rows = {}
        self.active = None
        self.closed = False
        self.pid = None

    def _prune(self):
        now = time.monotonic()
        for key, row in list(self.rows.items()):
            if key != self.active and now - row['_at'] > self.TTL:
                del self.rows[key]

    def snapshot(self, ident=None):
        self.core.assert_running()
        with self.lock:
            self._prune()
            if ident is not None:
                row = self.rows.get(ident)
                return copy.deepcopy({k: v for k, v in row.items() if not k.startswith('_')}) if row else {
                    'id': ident, 'status': 'MISSING', 'message': '转写已过期或服务已重启；没有重新识别。'}
            return dict(id='speech-input', busy=self.active is not None, active_id=self.active,
                        backend='SenseVoice int8 / CPU', local=True, resident=False,
                        pid=self.pid, memory=process_memory(self.pid) if self.pid else None,
                        max_seconds=MAX_SECONDS, threads=2, memory_limit_bytes=MEMORY_LIMIT,
                        result_ttl_seconds=self.TTL, languages=sorted(LANGUAGES))

    def submit(self, payload):
        self.core.assert_running()
        action, ident, pcm = validate(payload)
        with self.lock:
            if self.closed:
                raise SpeechError('语音识别正在退出。')
            self._prune()
            row = self.rows.get(ident)
            if action in {'cancel', 'forget'}:
                if row:
                    row['_cancel'].set()
                    row.pop('text', None)
                    row.update(status='CANCELLED' if action == 'cancel' else 'FORGOTTEN')
                else:
                    self._admit()
                    self.rows[ident] = dict(id=ident, status='CANCELLED', _at=time.monotonic(),
                                            _cancel=threading.Event())
                return self.snapshot(ident)
            signature = hashlib.sha256(pcm + payload['language'].encode()).hexdigest()
            if row:
                if row.get('_signature') != signature:
                    raise SpeechError('编号已使用或已取消；未再次识别。')
                return self.snapshot(ident)
            if self.active is not None:
                raise SpeechError('已有录音正在识别，请先完成或取消。')
            self._admit()
            cancel = threading.Event()
            self.rows[ident] = dict(id=ident, status='RUNNING', local=True, language=payload['language'],
                                   audio_seconds=len(pcm)/32000, _signature=signature,
                                   _at=time.monotonic(), _cancel=cancel)
            self.active = ident
            threading.Thread(target=self._run, args=(ident, pcm, payload['language'], cancel),
                             name='jarvis-speech-input', daemon=True).start()
            return self.snapshot(ident)

    def _admit(self):
        if len(self.rows) >= 64:
            raise SpeechError('语音回执容量已满，请稍后再试。')

    def _run(self, ident, pcm, language, cancel):
        started = time.monotonic()
        from .runtime_admission import coordinator
        lease = None
        try:
            lease = coordinator(self.core).acquire('stt', 768, owner=ident)
            result = self.runner(pcm, language, cancel)
            self.core.assert_running()
            if not isinstance(result, dict) or not isinstance(result.get('text'), str) or len(result['text']) > 4000:
                raise SpeechError('识别结果无效。')
            with self.lock:
                row = self.rows[ident]
                if not cancel.is_set() and not self.closed:
                    row.update(result, status='SUCCEEDED', elapsed_seconds=round(time.monotonic()-started, 3))
        except Exception:
            with self.lock:
                if not cancel.is_set():
                    self.rows[ident].update(status='FAILED', message='本地识别未完成。请检查模型和内存，或继续打字；没有上传录音。')
        finally:
            if lease is not None: coordinator(self.core).release(lease)
            with self.lock:
                if self.active == ident:
                    self.active = None
                self.rows[ident]['_at'] = time.monotonic()

    def _recognize(self, pcm, language, cancel):
        available = memory_snapshot()
        if min(available['available_bytes'], available['commit_available_bytes']) < 2 * 1024**3:
            raise SpeechError('识别需至少 2 GiB 可用内存。')
        process = job = None
        done = threading.Event()
        received = []
        try:
            job = ProcessJob(memory_limit=MEMORY_LIMIT)
            env = {key: value for key, value in os.environ.items()
                   if key.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATH'}}
            env.update(PYTHONPATH=os.pathsep.join(str(Path(p).absolute()) for p in sys.path if p),
                       PYTHONIOENCODING='utf-8', OMP_NUM_THREADS='2')
            process = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-B', '-u',
                                        str(Path(__file__).with_name('speech_input_worker.py'))],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       env=env, close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
            job.attach(process)
            with self.lock:
                self.pid = process.pid
            packet = json.dumps(dict(pcm=base64.b64encode(pcm).decode(), language=language,
                                     model_root=str(self.model_root) if self.model_root else None)).encode()
            def exchange():
                try:
                    process.stdin.write(packet)
                    process.stdin.close()
                    # Bound output before decoding. A child cannot fill Host memory.
                    received.append(process.stdout.read(16385))
                except (OSError, ValueError):
                    pass
                finally:
                    done.set()
            thread = threading.Thread(target=exchange, daemon=True)
            thread.start()
            deadline = time.monotonic() + 45
            peak = 0
            while not done.wait(.05):
                self.core.assert_running()
                if cancel.is_set() or self.closed or time.monotonic() > deadline:
                    raise SpeechError('识别已停止或超时。')
                sample = process_memory(process.pid)
                if sample:
                    peak = max(peak, sample['peak_working_set_bytes'])
            if cancel.is_set() or not received or len(received[0]) > 16384:
                raise SpeechError('识别输出无效。')
            result = json.loads(received[0])
            process.wait(timeout=2)
            if (process.returncode or set(result) != {'text', 'backend', 'vad', 'speech_seconds'}
                    or result['vad'] != 'silero' or type(result['speech_seconds']) not in (int, float)
                    or not 0 <= result['speech_seconds'] <= 21):
                raise SpeechError('识别进程未正常结束。')
            return {**result, 'peak_working_set_bytes': peak, 'model_released': True}
        finally:
            if job:
                job.kill()
            if process:
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                for stream in (process.stdin, process.stdout):
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
            if job:
                job.close()
            with self.lock:
                self.pid = None

    def close(self):
        with self.lock:
            self.closed = True
            for row in self.rows.values():
                row['_cancel'].set()
                row.pop('text', None)
                if row['status'] == 'RUNNING':
                    row['status'] = 'CANCELLED'
