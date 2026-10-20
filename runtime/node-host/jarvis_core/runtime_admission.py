"""One lightweight Host resource admission registry, not OS memory reservation."""
from contextlib import contextmanager
import threading
import time
import uuid

from .policy import CoreError
from .resources import MIB, memory_snapshot

_creation = threading.Lock()


class RuntimeAdmission:
    def __init__(self, probe=memory_snapshot):
        self.probe = probe
        self.lock = threading.RLock()
        self.active = {}
        self.waiting = {}
        self.order = []

    def acquire(self, lane, estimate_mib, *, owner=''):
        with self.lock:
            foreground = lane == 'chat'
            group = 'background' if lane in {'task','growth'} else lane
            capacity = 2 if foreground else 1
            key=(lane,owner)
            blocked=(sum(r['group']==group for r in self.active.values()) >= capacity)
            turn=group=='background' and self.order and self.order[0]!=key
            if blocked or turn:
                if group=='background' and key not in self.order:self.order.append(key)
                self.waiting[lane]='lane_busy'
                raise CoreError('resource_wait','资源通道忙，等待已有任务释放。')
            try:
                sample=self.probe()
                available=min(sample['available_bytes'],sample['commit_available_bytes'])
            except (KeyError,ValueError,OSError,TypeError):
                self.waiting[lane]='sample_unavailable'
                raise CoreError('resource_wait','资源采样不可用，未启动新后台工作。') from None
            # Existing process memory is already reflected in available bytes;
            # keeping all estimates is conservative during startup races.
            reserved=sum(r['estimate_mib'] for r in self.active.values())
            headroom=256 if foreground else 1024
            if available < (reserved+estimate_mib+headroom)*MIB:
                self.waiting[lane]='memory_pressure'
                raise CoreError('resource_wait','内存余量不足，保留前台空间后等待。')
            ident=uuid.uuid4().hex
            self.active[ident]={'lane':lane,'group':group,'owner':owner,'estimate_mib':estimate_mib,'since':time.monotonic()}
            self.waiting.pop(lane,None)
            if key in self.order:self.order.remove(key)
            return ident

    def release(self, ident):
        with self.lock:self.active.pop(ident,None)

    def clear_waiters(self,lane,keep_owner=None):
        with self.lock:
            self.order=[key for key in self.order if key[0]!=lane or key[1]==keep_owner]
            if not any(key[0]==lane for key in self.order):self.waiting.pop(lane,None)

    @contextmanager
    def lease(self,lane,estimate_mib,*,owner=''):
        ident=self.acquire(lane,estimate_mib,owner=owner)
        try:yield ident
        finally:self.release(ident)

    def snapshot(self):
        with self.lock:
            return {'active':list(self.active.values()),'waiting':dict(self.waiting),
                    'background_wait_order':[key[0] for key in self.order],
                    'foreground_reserve_mib':1024,'kind':'host_estimated_admission',
                    'os_reservation':False}


def coordinator(core):
    with _creation:
        if not hasattr(core,'runtime_admission'):
            core.runtime_admission=RuntimeAdmission()
        return core.runtime_admission
