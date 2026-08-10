"""Package entry for ``energy.pue_tracker``.

Canonical implementation lives at ``src/energy/pue_tracker.py``. Root-level
``energy/`` is on PYTHONPATH ahead of ``src/``, so this shim keeps
``from energy.pue_tracker import …`` on the shipped path without duplicating
logic.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "energy" / "pue_tracker.py"
_NAME = "_colossus_src_energy_pue_tracker"
_spec = importlib.util.spec_from_file_location(_NAME, _SRC)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot load PUE tracker from {_SRC}")
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_NAME] = _mod
_spec.loader.exec_module(_mod)

PUE_GATE_LIMIT = _mod.PUE_GATE_LIMIT
PUE_WARN_THRESHOLD = _mod.PUE_WARN_THRESHOLD
PUE_ALERT_CYCLES = _mod.PUE_ALERT_CYCLES
WINDOW_SECONDS = _mod.WINDOW_SECONDS
DEFAULT_COOLING_RATIO = _mod.DEFAULT_COOLING_RATIO
DEFAULT_PDU_RATIO = _mod.DEFAULT_PDU_RATIO
DEFAULT_LIGHTING_RATIO = _mod.DEFAULT_LIGHTING_RATIO
PUETracker = _mod.PUETracker

__all__ = [
    "PUE_GATE_LIMIT",
    "PUE_WARN_THRESHOLD",
    "PUE_ALERT_CYCLES",
    "WINDOW_SECONDS",
    "DEFAULT_COOLING_RATIO",
    "DEFAULT_PDU_RATIO",
    "DEFAULT_LIGHTING_RATIO",
    "PUETracker",
]
