"""Independent deterministic control storage; OS privilege separation is pending."""

from .store import SafetyError, SafetyStore

__all__ = ["SafetyError", "SafetyStore"]
