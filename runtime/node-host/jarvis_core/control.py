"""Compatibility bridge to the independently callable control store."""
from contextlib import contextmanager
from pathlib import Path
import sys

from .policy import CoreError

PACKAGE = str(Path(__file__).resolve().parents[2] / "sovereignty-supervisor")
if PACKAGE not in sys.path:
    sys.path.insert(0, PACKAGE)
from jarvis_safety import SafetyError, SafetyStore


class ControlGate:
    def __init__(self, data_dir):
        self.store = SafetyStore(data_dir)

    def call(self, method, *args, **kwargs):
        try:
            return getattr(self.store, method)(*args, **kwargs)
        except SafetyError as exc:
            raise CoreError(exc.code, str(exc)) from exc

    @contextmanager
    def effect_guard(self, node_id, epoch):
        try:
            with self.store.effect_guard(node_id, epoch):
                yield
        except SafetyError as exc:
            raise CoreError(exc.code, str(exc)) from exc
