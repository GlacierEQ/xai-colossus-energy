# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
"""tests/test_pue_tracker.py — Issue #7 acceptance criteria."""

import os
import json
import time
import tempfile
from unittest.mock import MagicMock
from electricity.pue_tracker import (
    PUETracker, PUE_LIMIT, ALERT_SUSTAIN_SECS, LOG_INTERVAL_SECS,
)


def _tracker(it_kw=100_000.0, cooling_kw=None, sb=None, dispatch=None, log_dir=None):
    if log_dir is None:
        log_dir = tempfile.mkdtemp()
    cooling_kw = cooling_kw if cooling_kw is not None else it_kw * 0.35
    return PUETracker(
        it_load_fn=lambda: it_kw,
        cooling_load_fn=lambda: cooling_kw,
        sb=sb,
        mcp_dispatch=dispatch,
        log_dir=log_dir,
    )


def test_pue_calculation_known_inputs():
    """PUE = (it + cooling + pdu_overhead) / it."""
    it_kw      = 100.0
    cooling_kw = 35.0
    pdu_kw     = it_kw * 0.04   # 4.0
    expected   = (it_kw + cooling_kw + pdu_kw) / it_kw  # 1.39
    t = _tracker(it_kw=it_kw, cooling_kw=cooling_kw)
    assert abs(t.compute_pue() - expected) < 0.001


def test_pue_below_limit_no_alert():
    dispatch = MagicMock()
    t = _tracker(it_kw=100_000.0, cooling_kw=35_000.0, dispatch=dispatch)
    # PUE ≈ 1.39 — well below 1.45
    for _ in range(10):
        t.tick()
    dispatch.assert_not_called()


def test_pue_above_limit_alert_fires_after_sustain():
    dispatch = MagicMock()
    # cooling_kw = 50% of it → PUE ≈ 1.54 (above 1.45)
    t = _tracker(it_kw=100_000.0, cooling_kw=50_000.0, dispatch=dispatch)
    # Fake _over_limit_since to simulate 301 seconds ago
    t._over_limit_since = time.time() - (ALERT_SUSTAIN_SECS + 1)
    t.tick()
    dispatch.assert_called_once()
    args = dispatch.call_args[0]
    assert args[0] == "pue_alert"
    assert args[1]["pue"] > PUE_LIMIT


def test_pue_alert_not_fired_twice():
    dispatch = MagicMock()
    t = _tracker(it_kw=100_000.0, cooling_kw=50_000.0, dispatch=dispatch)
    t._over_limit_since = time.time() - (ALERT_SUSTAIN_SECS + 1)
    t.tick()   # fires alert
    t.tick()   # must NOT fire again
    assert dispatch.call_count == 1


def test_log_written_every_60s(tmp_path):
    t = _tracker(log_dir=str(tmp_path))
    t._last_log_ts = 0  # force write on first tick
    t.tick()
    logs = list(tmp_path.glob("pue_*.jsonl"))
    assert len(logs) == 1
    with open(logs[0]) as f:
        row = json.loads(f.readline())
    assert "pue" in row and "ts" in row


def test_compute_pue_never_divides_by_zero():
    """it_load floored at 1 kW even if callback returns 0."""
    t = _tracker(it_kw=0.0, cooling_kw=0.0)
    pue = t.compute_pue()
    assert pue > 0  # must not raise ZeroDivisionError
