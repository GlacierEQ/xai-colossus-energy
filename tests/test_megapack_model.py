"""tests/test_megapack_model.py — Issue #2 acceptance criteria.

Gauntlet: grid drop at tick 5, assert discharge starts by tick 6.
"""

from unittest.mock import MagicMock
from megapack_buffer.megapack_model import MegapackModel, MegapackConfig, MegapackEvent, CRITICAL_SOC_PCT

DEFAULT_CFG = MegapackConfig(
    capacity_mwh=560.0,
    max_discharge_mw=140.0,
    max_charge_mw=70.0,
    failover_threshold_pct=90.0,
    initial_soc_pct=80.0,
)


def _make_model(sb=None, dispatch=None):
    return MegapackModel(config=DEFAULT_CFG, sb=sb, mcp_dispatch=dispatch)


def test_no_discharge_below_threshold():
    m = _make_model()
    for _ in range(5):
        snap = m.tick(grid_utilisation_pct=85.0)
    assert not m.discharging


def test_discharge_starts_at_threshold():
    m = _make_model()
    snap = m.tick(grid_utilisation_pct=91.0)
    assert m.discharging
    assert MegapackEvent.DISCHARGE_START.value in snap["events"]


def test_gauntlet_grid_drop_tick_5_discharge_by_tick_6():
    """Grid runs normal for 5 ticks, overloads on tick 5 — discharge must start."""
    m = _make_model()
    for i in range(1, 5):          # ticks 1-4: normal
        snap = m.tick(grid_utilisation_pct=70.0)
        assert not m.discharging, f"Unexpected discharge at tick {i}"
    # tick 5: grid overload
    snap = m.tick(grid_utilisation_pct=95.0)
    assert m.discharging, "Discharge must start on tick 5 (overload tick)"
    assert MegapackEvent.DISCHARGE_START.value in snap["events"]


def test_recharge_on_grid_restore():
    m = _make_model()
    m.tick(grid_utilisation_pct=95.0)   # start discharge
    m.tick(grid_utilisation_pct=50.0, grid_restored=True)  # restore
    assert m.charging


def test_critical_soc_event_fires():
    dispatch = MagicMock()
    m = _make_model(dispatch=dispatch)
    m.soc_pct = CRITICAL_SOC_PCT + 0.5  # just above critical
    m._model = m  # self-reference for soc (model IS the test object)
    # Force SoC to critical
    m.soc_pct = CRITICAL_SOC_PCT - 0.1
    m._critical_emitted = False
    m.tick(grid_utilisation_pct=70.0)   # will detect critical
    assert dispatch.called
    call_event = dispatch.call_args[0][0]
    assert call_event == MegapackEvent.CRITICAL_SOC.value


def test_discharge_start_writes_to_supabase():
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value = MagicMock()
    m = _make_model(sb=sb)
    m.tick(grid_utilisation_pct=92.0)
    sb.table.assert_called_with("audit_events")
