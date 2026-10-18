"""Bounded process-local timing observations; never task authority or replay.

No prompt, result, model key, path or caller ID is retained. Monotonic durations
are distinct from persisted queue age (wall time, which may change across boot).
"""
from collections import Counter, deque
from datetime import datetime, timezone
import math
import threading
import time
import uuid


class RuntimeMetrics:
    def __init__(self, *, clock=time.monotonic, capacity=200):
        self.clock = clock
        self.lock = threading.Lock()
        self.samples = deque(maxlen=capacity)
        self.active = {}
        self.counters = Counter()
        self.started = self.last = clock()
        self.overlap_seconds = 0.0
        self.started_at = datetime.now(timezone.utc).isoformat()

    def _advance(self, now):
        lanes = {row['lane'] for row in self.active.values()}
        if lanes == {'chat', 'task'}:
            self.overlap_seconds += max(0, now-self.last)
        self.last = now

    def begin(self, lane, *, queue_wait_ms=None):
        if lane not in {'chat', 'task'}:
            raise ValueError('Invalid runtime lane')
        with self.lock:
            now = self.clock(); self._advance(now)
            token = uuid.uuid4().hex
            self.active[token] = {'lane': lane, 'start': now, 'queue_wait_ms': queue_wait_ms}
            self.counters[lane+'_started'] += 1
            return token

    def finish(self, token, status):
        with self.lock:
            now = self.clock(); self._advance(now)
            row = self.active.pop(token, None)
            if row is None:
                return
            status = status if status in {'SUCCEEDED','CONFIRMED','FAILED','CANCELLED','UNKNOWN'} else 'UNKNOWN'
            self.samples.append({'lane': row['lane'], 'status': status,
                                 'duration_ms': round(max(0, now-row['start'])*1000, 2),
                                 'queue_wait_ms': row['queue_wait_ms']})
            self.counters[row['lane']+'_finished'] += 1

    def event(self, name):
        if name not in {'chat_busy','http_wait_timeout','chat_thread_failed','calculation_completed'}:
            raise ValueError('Invalid runtime counter')
        with self.lock:
            self.counters[name] += 1

    def snapshot(self):
        def stats(rows, field):
            values = sorted(row[field] for row in rows if row.get(field) is not None)
            return {'samples': len(values), 'p50_ms': values[math.ceil(len(values)*.5)-1] if values else None,
                    'p95_ms': values[math.ceil(len(values)*.95)-1] if values else None,
                    'max_ms': values[-1] if values else None}
        with self.lock:
            now = self.clock(); self._advance(now)
            result = {'scope': 'host_lifetime', 'started_at': self.started_at,
                      'uptime_seconds': round(max(0,now-self.started),2), 'sample_capacity': self.samples.maxlen,
                      'counters': dict(self.counters), 'overlap_seconds': round(self.overlap_seconds,3), 'lanes': {}}
            for lane in ('chat', 'task'):
                rows = [r for r in self.samples if r['lane']==lane]
                active = [r for r in self.active.values() if r['lane']==lane]
                result['lanes'][lane] = {'active': len(active), 'oldest_active_ms': round(max((now-r['start'] for r in active),default=0)*1000,2),
                    'duration': stats(rows,'duration_ms'), 'queue_wait': stats(rows,'queue_wait_ms'),
                    'outcomes': dict(Counter(r['status'] for r in rows))}
            return result
