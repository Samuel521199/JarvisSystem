"""Bounded PCM composition; explicit silence and short edge fades, no time stretching."""
from array import array
import sys

from .speech_contract import SpeechError


RATE=24000


class SpeechAudio:
    def __init__(self,max_seconds):
        self.limit=max_seconds*RATE;self.pcm=bytearray();self.timeline=[]

    def _append(self,pcm,row):
        if len(pcm)%2 or len(self.pcm)//2+len(pcm)//2>self.limit:raise SpeechError('分段语音与停顿总长超过输出上限。')
        start=len(self.pcm)//2;self.pcm.extend(pcm)
        self.timeline.append(dict(row,start_sample=start,end_sample=len(self.pcm)//2,
                                  start_seconds=start/RATE,end_seconds=len(self.pcm)/2/RATE))

    def pause(self,milliseconds):
        self._append(bytes(milliseconds*RATE//1000*2),dict(type='pause',milliseconds=milliseconds))

    def speech(self,pcm,row,*,fade):
        if not pcm or len(pcm)%2:raise SpeechError('分段语音 PCM 无效。')
        if fade:
            samples=array('h');samples.frombytes(pcm)
            if sys.byteorder!='little':samples.byteswap()
            count=min(120,len(samples)//2)  # 5ms, no trimming of words/tails or artificial rate change.
            for i in range(count):
                gain=i/max(1,count-1);samples[i]=int(samples[i]*gain);samples[-1-i]=int(samples[-1-i]*gain)
            if sys.byteorder!='little':samples.byteswap()
            pcm=samples.tobytes()
        self._append(pcm,row)
