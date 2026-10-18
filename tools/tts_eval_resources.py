"""Evaluation compatibility import of the shared, optional WDDM reader."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "runtime/node-host"))
from jarvis_core.gpu_memory import GpuMemory
