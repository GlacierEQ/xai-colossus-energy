# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
"""tests/test_power_budget.py — Issue #3 acceptance criteria."""

from unittest.mock import MagicMock, call
from power_budget import GridSegment, PowerBudgetModel, ALERT_THRESHOLD_PCT


def _make_model(sb=None, dispatch=None):
    m = PowerBudgetModel(sb=sb, mcp_dispatch=dispatch)
    m.register_segment(GridSegment("utility-a", "utility",  capacity_mw=900.0, current_load_mw=0.0))
    m.register_segment(GridSegment("gas-b",    "gas",       capacity_mw=100.0, current_load_mw=0.0))
    m.register_segment(GridSegment("solar-c",  "renewable", capacity_mw=12.0,  current_load_mw=0.0))
    return m


def test_headroom_computed_correctly():
    seg = GridSegment("x", "utility", capacity_mw=100.0, current_load_mw=70.0)
    assert seg.headroom_mw == 30.0
    assert seg.utilisation_pct == 70.0


def test_tick_returns_all_segments():
    m = _make_model()
    rows = m.tick()
    assert len(rows) == 3
    segment_ids = {r["segment_id"] for r in rows}
    assert {"utility-a", "gas-b", "solar-c"} == segment_ids


def test_tick_upserts_supabase():
    sb = MagicMock()
    sb.table.return_value.upsert.return_value.execute.return_value = MagicMock()
    m = _make_model(sb=sb)
    m.tick()
    sb.table.assert_called_with("energy_budget")
    sb.table.return_value.upsert.assert_called_once()


def test_budget_breach_alert_fires_above_threshold():
    dispatch = MagicMock()
    m = _make_model(dispatch=dispatch)
    # Load utility-a to 92% (above ALERT_THRESHOLD_PCT=90%)
    m.update_segment("utility-a", current_load_mw=900.0 * 0.92)
    m.tick()
    dispatch.assert_called_once()
    args = dispatch.call_args[0]
    assert args[0] == "budget_breach"
    assert args[1]["segment_id"] == "utility-a"


def test_no_alert_below_threshold():
    dispatch = MagicMock()
    m = _make_model(dispatch=dispatch)
    m.update_segment("utility-a", current_load_mw=900.0 * 0.85)  # 85% — below threshold
    m.tick()
    dispatch.assert_not_called()


def test_update_unknown_segment_does_not_raise():
    m = _make_model()
    m.update_segment("nonexistent", 500.0)  # must not raise


def test_total_load_and_capacity():
    m = _make_model()
    m.update_segment("utility-a", 800.0)
    m.update_segment("gas-b",     80.0)
    assert abs(m.total_load_mw - 880.0) < 0.001
    assert abs(m.total_capacity_mw - 1012.0) < 0.001
