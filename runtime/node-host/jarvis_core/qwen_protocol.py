"""Bounded JSONL/PCM reader for speech.cpp worker protocol 3."""
import base64
import json
import queue
import threading
import time

from .speech_contract import SpeechError


class NativeProtocol:
    def __init__(self,stream):
        self.rows=queue.Queue(maxsize=32)
        def read():
            try:
                while True:
                    line=stream.readline(1_000_001)
                    if not line or len(line)>1_000_000: raise SpeechError('原生语音协议中断或超过上限。')
                    value=json.loads(line)
                    if not isinstance(value,dict): raise ValueError()
                    self.rows.put(value)
            except Exception:
                self.rows.put(SpeechError('原生语音协议读取失败。'))
        threading.Thread(target=read,name='qwen-native-output',daemon=True).start()

    def next(self,deadline):
        try: value=self.rows.get(timeout=max(.001,deadline-time.monotonic()))
        except queue.Empty: raise SpeechError('原生语音操作超时。')
        if isinstance(value,Exception): raise value
        return value

    def audio(self,ident,max_seconds,timeout):
        started=time.monotonic(); deadline=started+timeout; data=bytearray(); seq=0; first=None
        for _ in range(10000):
            row=self.next(deadline)
            if row.get('id')!=ident: raise SpeechError('原生语音回执标识不符。')
            kind=row.get('type')
            if kind=='chunk':
                if type(row.get('seq')) is not int or row['seq']!=seq: raise SpeechError('原生语音分片次序不符。')
                try: chunk=base64.b64decode(row['pcm'],validate=True)
                except Exception: raise SpeechError('原生语音 PCM 无效。')
                if not chunk or len(chunk)%2: raise SpeechError('原生语音 PCM 长度无效。')
                data.extend(chunk); seq+=1
                if first is None: first=time.monotonic()-started
                if len(data)>max_seconds*24000*2: raise SpeechError('原生语音输出超过时长上限。')
            elif kind=='end':
                if row.get('stop')!='complete' or type(row.get('samples')) is not int or row['samples']!=len(data)//2 or not data:
                    raise SpeechError('原生语音未完整完成；不交付截断音频。')
                return bytes(data),first
            elif kind!='progress': raise SpeechError('原生语音推理失败或取消。')
        raise SpeechError('原生语音回执数量超过上限。')
