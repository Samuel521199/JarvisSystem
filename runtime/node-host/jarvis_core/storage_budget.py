"""A thread-local SQLite wait budget for short interactive control paths.

Limits lock waiting, not execution time or OS scheduling. Nested calls share
one deadline; background transactions retain their existing default timeout.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import time

_deadline=ContextVar('jarvis_storage_deadline',default=None)


@contextmanager
def budget(seconds=.08):
    deadline=time.monotonic()+seconds
    parent=_deadline.get()
    token=_deadline.set(min(parent,deadline) if parent is not None else deadline)
    try:yield
    finally:_deadline.reset(token)


def timeout(default):
    deadline=_deadline.get()
    return min(default,max(0,deadline-time.monotonic())) if deadline is not None else default


def interactive(function):
    @wraps(function)
    def call(*args,**kwargs):
        with budget():return function(*args,**kwargs)
    return call
