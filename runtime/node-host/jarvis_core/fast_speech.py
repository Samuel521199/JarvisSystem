"""Low-latency local TTS shares the owned-process lifecycle, not the heavy model."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

from .speech import SpeechService
from .speech_contract import SpeechError, validate_synthesis


class FastSpeechService(SpeechService):
    component_id = 'zipvoice'
    worker_relative = 'adapters/speech/zipvoice/worker.py'
    api_path = '/api/speech/fast'
    ready_message = 'ZipVoice 备用语音已加载；需要时手动使用，用完可停止释放内存。'

    def snapshot(self):
        value = super().snapshot()
        value.update(usage_role='fallback', auto_start=False)
        return value

    def _reload_profile(self, *, strict):
        try:
            cfg = json.loads(self.config_path.read_text(encoding='utf-8'))
            if cfg['schema_version'] != 1 or cfg['id'] != self.component_id or cfg['device'] != 'cpu': raise ValueError()
            for key in ('model_root','environment_root'):
                if not isinstance(cfg[key], str) or not Path(cfg[key]).is_absolute(): raise ValueError()
            for key, maximum in (('threads',8),('max_text_chars',180),('max_reference_seconds',15),('max_output_seconds',60),
                                 ('request_timeout_seconds',60),('startup_timeout_seconds',120),('minimum_available_memory_gib',8)):
                if type(cfg[key]) is not int or not 1 <= cfg[key] <= maximum: raise ValueError()
            if cfg['num_steps'] != 4 or not cfg['files'] or sum(x['size_bytes'] for x in cfg['files']) > 400_000_000: raise ValueError()
            for row in cfg['files']:
                path = PurePosixPath(row['path'])
                if path.is_absolute() or '..' in path.parts or '\\' in row['path'] or ':' in row['path']: raise ValueError()
                if type(row['size_bytes']) is not int or row['size_bytes'] <= 0 or len(row['sha256']) != 64: raise ValueError()
            if cfg['reference_file'] not in {r['path'] for r in cfg['files']}: raise ValueError()
            self.cfg = cfg; self.config_error = None
        except (OSError, ValueError, KeyError, TypeError):
            self.config_error = '快速语音配置缺失或无效；其他模块仍可使用。'
            if strict: raise SpeechError(self.config_error)

    def installed(self):
        if self.config_error: return False
        cfg = self.cfg
        try:
            marker = json.loads((Path(cfg['environment_root']) / 'jarvis-zipvoice-ready.json').read_text(encoding='utf-8'))
            expected = hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest()
            exe = Path(cfg['environment_root']) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            return marker.get('profile_sha256') == expected and exe.is_file() and all(
                (Path(cfg['model_root']) / row['path']).stat().st_size == row['size_bytes'] for row in cfg['files'])
        except (OSError, ValueError): return False

    def _prepare(self, epoch):
        self._verify_files(epoch)

    def default_reference(self):
        return Path(self.cfg['model_root']) / self.cfg['reference_file']

    def parse_synthesis(self, payload):
        # No free-text emotion instructions on the fast route; never silently escalate to CosyVoice.
        value = validate_synthesis(payload)
        if value['mode'] != 'clone' or value['emotion'] != 'neutral':
            raise SpeechError('快速语音使用自然表达，不支持文字情绪指令；增强表达可单独使用 CosyVoice3。')
        if len(value['text']) > self.cfg['max_text_chars']:
            raise SpeechError('快速语音每次最多 ' + str(self.cfg['max_text_chars']) + ' 字，请分成短句。')
        return value
