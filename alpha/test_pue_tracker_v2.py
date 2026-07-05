# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
"""tests/test_pue_tracker_v2.py — Issue #7 acceptance tests"""

import logging
import time
import pytest
from unittest.mock import MagicMock

import sys, os
SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from energy.pue_tracker import (
    PUETracker, PUE_GATE_LIMIT, PUE_WARN_THRESHOLD, PUE_ALERT_CYCLES
)


# ── Basic recording ───────────────────────────────────────────────────────────

def test_instantaneous_pue_correct():
    t = PUETracker(cooling_ratio=0.35, pdu_ratio=0.04, lighting_ratio=0.005)
    pue = t.record(it_load_kw=100_000.0)
    expected = (100_000 + 35_000 + 4_000 + 500) / 100_000  # = 1.395
    assert abs(pue - expected) < 0.0001


def test_pue_24h_avg_single_reading():
    t = PUETracker()
    pue = t.record(it_load_kw=100_000.0)
    assert t.pue_24h_avg == pytest.approx(pue)


def test_pue_24h_avg_multiple_readings():
    t = PUETracker()
    vals = []
    for load in [80_000, 100_000, 120_000]:
        vals.append(t.record(it_load_kw=float(load)))
    assert t.pue_24h_avg == pytest.approx(sum(vals) / len(vals))


# ── Gate pass/fail ────────────────────────────────────────────────────────────

def test_gate_passing_at_low_pue():
    # PUE = 1.395 with defaults — below 1.45 gate
    t = PUETracker(cooling_ratio=0.35, pdu_ratio=0.04, lighting_ratio=0.005)
    t.record(it_load_kw=100_000.0)
    assert t.is_gate_passing is True


def test_gate_failing_at_high_pue():
    # Force high cooling ratio to exceed gate
    t = PUETracker(cooling_ratio=0.50, pdu_ratio=0.04, lighting_ratio=0.005)
    t.record(it_load_kw=100_000.0)  # PUE = 1.545
    assert t.is_gate_passing is False


def test_no_readings_gate_passes_vacuously():
    """is_gate_passing returns False (not True) when there are no readings."""
    t = PUETracker()
    assert t.is_gate_passing is False  # None avg → False


# ── Hysteresis ──────────────────────────────────────────────────────────────

def test_critical_fires_after_5_consecutive_readings(caplog):
    t = PUETracker(cooling_ratio=0.50, pdu_ratio=0.04, lighting_ratio=0.005)
    with caplog.at_level(logging.ERROR, logger="PUETracker"):
        for _ in range(PUE_ALERT_CYCLES):
            t.record(it_load_kw=100_000.0)
    assert any("GATE FAIL" in r.message or "CRITICAL" in r.message
               for r in caplog.records)


# ── Supabase integration (mocked) ──────────────────────────────────────────

def test_supabase_telemetry_written_when_client_available():
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.insert.return_value = mock_table
    mock_table.execute.return_value = {}

    t = PUETracker(sb=mock_sb)
    t.record(it_load_kw=100_000.0)

    mock_sb.table.assert_called_with("energy_telemetry")
    mock_table.insert.assert_called_once()


def test_no_crash_without_supabase_client():
    t = PUETracker(sb=None)
    pue = t.record(it_load_kw=100_000.0)
    assert pue > 1.0  # ran without crash
