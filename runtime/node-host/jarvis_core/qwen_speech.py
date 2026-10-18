"""Owned native Vulkan TTS, primary role, explicitly loaded and independently stopped."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

from . import policy
from .gpu_memory import GpuMemory
from .process_memory import process_memory
from .qwen_speech_contract import VOICES, EMOTIONS, LANGUAGES, EMOTION_TAGS, validate, preview, MAX_SEGMENTS, MAX_PAUSE_MS, MAX_DIRECTION_CHARS
from .speech import SpeechService
from .speech_contract import SpeechError


class QwenSpeechService(SpeechService):
    component_id='qwen-tts'
    worker_relative='adapters/speech/qwen/worker.py'
    api_path='/api/speech/primary'
    ready_message='Qwen 主力语音已加载，可选择音色与情绪；用完可独立停止。'

    def __init__(self,*args,**kwargs):
        self.gpu=None; self.gpu_pid=None; self.reader=None
        super().__init__(*args,**kwargs)
        from .readout import ReadoutLane
        self.reader=ReadoutLane(self)

    def _reload_profile(self,*,strict):
        try:
            cfg=json.loads(self.config_path.read_text(encoding='utf-8'))
            if cfg['schema_version']!=1 or cfg['id']!=self.component_id or cfg['device'] not in ('Vulkan0','cpu'):
                raise ValueError()
            if cfg['backend_version']!='0.8.10': raise ValueError()
            for key in ('model_root','runtime_root','environment_root'):
                if not isinstance(cfg[key],str) or not Path(cfg[key]).is_absolute(): raise ValueError()
            for key,maximum in [('threads',8),('max_text_chars',180),('max_reference_seconds',15),('max_output_seconds',20),
                                ('request_timeout_seconds',60),('startup_timeout_seconds',120),('minimum_available_memory_gib',8)]:
                if type(cfg[key]) is not int or not 1<=cfg[key]<=maximum: raise ValueError()
            if len(cfg['files'])!=1 or cfg['files'][0]['path']!=cfg['model_file']: raise ValueError()
            if {r['path'] for r in cfg['runtime_files']}!={'speech.exe','speech.dll','speech.h','speech.lib'}: raise ValueError()
            for item in cfg['files']+cfg['runtime_files']:
                name=item['path']; path=PurePosixPath(name)
                if not isinstance(name,str) or len(path.parts)!=1 or path.is_absolute() or name in ('.','..') or '\\' in name or ':' in name:
                    raise ValueError()
                if type(item['size_bytes']) is not int or not 0<item['size_bytes']<=2_000_000_000: raise ValueError()
                if not isinstance(item['sha256'],str) or len(item['sha256'])!=64 or any(c not in '0123456789abcdef' for c in item['sha256']):
                    raise ValueError()
            self.cfg=cfg; self.config_error=None
        except (OSError,ValueError,KeyError,TypeError):
            self.config_error='Qwen 语音配置缺失或无效；其他模块仍可使用。'
            if strict: raise SpeechError(self.config_error)

    def installed(self):
        if self.config_error: return False
        try:
            exe=Path(self.cfg['environment_root'])/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            return exe.is_file() and all((Path(self.cfg[root])/row['path']).stat().st_size==row['size_bytes']
                for root,key in [('model_root','files'),('runtime_root','runtime_files')] for row in self.cfg[key])
        except OSError: return False

    def _prepare(self,epoch):
        self._verify_files(epoch)
        for row in self.cfg['runtime_files']:
            self._checkpoint(epoch)
            path=policy.safe_path(Path(self.cfg['runtime_root'])/row['path'],directory=False)
            if path.stat().st_nlink!=1 or path.stat().st_size!=row['size_bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
                raise SpeechError('语音运行库摘要不符，未启动。')

    def _validate_health(self,health,worker_pid):
        super()._validate_health(health,worker_pid)
        pid=health.get('inference_pid')
        if type(pid) is not int or pid==worker_pid or not self.engine.contains(pid) or health.get('protocol')!=3:
            raise SpeechError('原生语音进程不属于本次组件。')

    def parse_synthesis(self,payload): return validate(payload,min(180,self.cfg['max_text_chars']))

    def synthesis_request(self,parsed,row): return dict(parsed,id=row['id']),None

    def submit(self,payload):
        if isinstance(payload,dict) and payload.get('action')=='preview':
            self.core.assert_running()
            parsed=self.parse_synthesis(dict(payload,action='synthesize'))
            return dict(id=self.component_id,preview=preview(parsed))
        with self.lock:
            self.reader.expire()
            if self.reader.current and (not isinstance(payload,dict) or payload.get('action')!='stop'):
                raise SpeechError('聊天朗读正在使用语音组件；请先停止朗读，或用停止模型中断。')
            return super().submit(payload)

    def _close_gpu(self):
        if self.gpu: self.gpu.close()
        self.gpu=None; self.gpu_pid=None

    def snapshot(self):
        with self.lock:
            if self.reader:self.reader.expire()
            value=super().snapshot()
            broker_pid=value['pid']
            health=self.health or {}
            pid=health.get('inference_pid') if value['owned'] and self.worker_pid and health.get('pid')==self.worker_pid else None
            # Never query another process or keep a counter attached after its owned job exits.
            if pid and (type(pid) is not int or not self.engine.contains(pid)):
                self.stop(); self.state='failed'; value=super().snapshot(); pid=None
            if pid!=self.gpu_pid:
                self._close_gpu()
                if pid:
                    try: self.gpu=GpuMemory(pid)
                    except (OSError,AttributeError): self.gpu=None
                    self.gpu_pid=pid
            value.update(usage_role='primary',auto_start=False,device=self.cfg.get('device','unconfigured'),
                pid=pid,broker_pid=broker_pid,broker_memory=value['memory'],memory=process_memory(pid) if pid else None,
                gpu_memory=self.gpu.sample() if self.gpu else None,reference_default=None,
                readout_active=bool(self.reader and self.reader.current),
                capabilities={'voices':VOICES,'emotions':{k:v[0] for k,v in EMOTIONS.items()},'languages':LANGUAGES,
                              'emotion_tags':EMOTION_TAGS,'emotion_tag_scope':'persistent_independent_dimensions',
                              'expression_limits':dict(speech_segments=MAX_SEGMENTS,pause_ms=MAX_PAUSE_MS,direction_chars=MAX_DIRECTION_CHARS),
                              'cloning':False,'delivery':'complete_wav'})
            return value

    def stop(self):
        with self.lock:
            if self.reader:self.reader.release('CANCELLED','语音组件已停止；没有自动重放。')
            super().stop(); self._close_gpu()
