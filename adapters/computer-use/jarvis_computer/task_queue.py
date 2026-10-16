"""Compatibility entry for the shared core FIFO; no independent browser queue."""
from jarvis_core.task_queue import TaskQueue
from .protocol import ComputerError


class ComputerQueue(TaskQueue):
    def __init__(self, core, executor):
        super().__init__(core, executor, error_type=ComputerError)
