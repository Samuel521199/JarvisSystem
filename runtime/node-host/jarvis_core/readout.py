"""One expiring browser readout lease over the existing, owned Qwen component."""
import copy
import hashlib
import json
import time

from .readout_text import prepare
from .speech import SpeechService
from .speech_contract import SpeechError


class ReadoutLane:
    TTL=180
    def __init__(self,service):self.service=service;self.current=None;self.recent={}

    def remember(self,ident,status,message):
        self.recent[ident]=dict(id=ident,active=False,status=status,message=message)
        while len(self.recent)>8:self.recent.pop(next(iter(self.recent)))

    def release(self,status,message):
        if self.current:
            ident=self.current['id'];self.remember(ident,status,message)
            self.current=None

    def expire(self):
        if self.current and time.monotonic()>self.current['deadline']:
            busy=self.service.job is not None;self.release('EXPIRED','朗读会话已过期，没有自动重放。')
            if busy:self.service.stop()

    def _check_id(self,ident):
        if not isinstance(ident,str) or len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise SpeechError('朗读编号无效。')

    def _refresh(self):
        if self.current and self.current['items']:
            item=self.current['items'][-1];job=self.service.job or self.service.last_job
            if job and job['id']==item['job_id']:
                item['status']=job['status']
                if 'result' in job:item['result']=copy.deepcopy(job['result'])
                if 'message' in job:item['message']=job['message']
        if self.current and self.service.state=='failed':self.release('FAILED','本次语音失败，其他聊天与任务可继续。')

    def view(self,ident):
        self.service.core.assert_running()
        self._check_id(ident)
        with self.service.lock:
            self.service.snapshot()
            self.expire();self._refresh()
            if not self.current or self.current['id']!=ident:
                return copy.deepcopy(self.recent.get(ident,dict(id=ident,active=False,status='MISSING',message='此朗读会话已不可用。')))
            row=self.current;row['deadline']=time.monotonic()+self.TTL
            return dict(id=ident,active=True,status='ACTIVE',model_state=self.service.state,busy=self.service.job is not None,
                total=len(row['chunks']),items=copy.deepcopy(row['items']),spoken_chars=row['spoken_chars'],notices=row['notices'],
                voice=row['voice'],language=row['language'])

    def submit(self,payload):
        self.service.core.assert_running()
        if not isinstance(payload,dict):raise SpeechError('朗读请求必须是对象。')
        action=payload.get('action');ident=payload.get('id');self._check_id(ident)
        allowed={'start':{'action','id','text','voice','emotion','language','direction'},'next':{'action','id','index'},
                 'stop':{'action','id'},'finish':{'action','id'}}
        if not isinstance(action,str) or action not in allowed or set(payload)-allowed[action]:raise SpeechError('未知朗读操作或字段。')
        with self.service.lock:
            if self.service.closed:raise SpeechError('语音服务正在退出。')
            self.expire();self._refresh()
            if action=='start':
                prepared=prepare({k:v for k,v in payload.items() if k not in ('action','id')})
                signature=hashlib.sha256(json.dumps(prepared,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                if self.current:
                    if self.current['id']==ident and self.current['signature']==signature:return self.view(ident)
                    raise SpeechError('语音组件正被另一段朗读使用，请先停止原朗读。')
                if ident in self.recent:raise SpeechError('此朗读编号已结束；没有重新执行。')
                if self.service.job:raise SpeechError('语音组件已有操作，未抢占设置页或其他朗读。')
                self.current=dict(prepared,id=ident,signature=signature,deadline=time.monotonic()+self.TTL,items=[])
                try:
                    if self.service.state!='ready':SpeechService.submit(self.service,{'action':'start'})
                    return self.view(ident)
                except Exception:
                    self.release('FAILED','朗读未能启动。');raise
            if not self.current or self.current['id']!=ident:
                if action=='stop':
                    if ident not in self.recent:self.remember(ident,'CANCELLED','朗读已停止；迟到启动不再执行。')
                    return self.view(ident)  # Late stop never touches a newer lease.
                raise SpeechError('朗读会话已停止或过期，没有重放。')
            row=self.current;row['deadline']=time.monotonic()+self.TTL
            if action in ('stop','finish'):
                if set(payload)!={'action','id'}:raise SpeechError('朗读停止字段无效。')
                busy=self.service.job is not None
                if action=='finish' and (busy or len(row['items'])!=len(row['chunks']) or any(i['status']!='SUCCEEDED' for i in row['items'])):
                    raise SpeechError('朗读尚未完整生成，请继续或停止。')
                self.release('CANCELLED' if action=='stop' else 'FINISHED','朗读已停止。' if action=='stop' else '朗读已完成。')
                if busy:self.service.stop()
                return self.view(ident)
            index=payload.get('index')
            if type(index) is not int or not 0<=index<len(row['chunks']):raise SpeechError('朗读分段编号无效。')
            if index<len(row['items']):return self.view(ident)  # Idempotent receipt, not another inference.
            if index!=len(row['items']):raise SpeechError('请按顺序获取朗读分段。')
            if self.service.job:return self.view(ident)
            if self.service.state!='ready':raise SpeechError('语音组件尚未就绪。')
            value=SpeechService.submit(self.service,dict(row['chunks'][index],action='synthesize'))
            row['items'].append(dict(index=index,job_id=value['job']['id'],status=value['job']['status']))
            return self.view(ident)
