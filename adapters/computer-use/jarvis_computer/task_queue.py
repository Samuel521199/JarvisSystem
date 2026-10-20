"""Compatibility entry for the shared core FIFO; no independent browser queue."""
from jarvis_core.task_queue import TaskQueue
from .protocol import ComputerError


class ComputerQueue(TaskQueue):
    def __init__(self, core, executor, *, sample_executor=None, skill_executor=None, mcp_executor=None, team_executor=None, metrics=None):
        super().__init__(core, executor, error_type=ComputerError, sample_executor=sample_executor, skill_executor=skill_executor, mcp_executor=mcp_executor, team_executor=team_executor, metrics=metrics)
