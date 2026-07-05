"""tests/test_megapack_controller.py — Issue #6 acceptance criteria.

All four state transitions covered:
  IDLE → DISCHARGING
  IDLE → CHARGING
  DISCHARGING → IDLE
  DISCHARGING → FAULT (critical SoC)
  CHARGING → IDLE
  FAULT sticky until manual_reset()
  FAULT entry emits MCP event
"""

from unittest.mock import MagicMock
from megapack_controller import MegapackController, MegapackState
from megapack_model import MegapackConfig, CRITICAL_SOC_PCT

DEFAULT_CFG = MegapackConfig(initial_soc_pct=80.0)


def _ctrl(dispatch=None):
    return MegapackController(
        config=DEFAULT_CFG,
        mcp_dispatch=dispatch,
        discharge_threshold_pct=90.0,
        charge_threshold_pct=60.0,
    )


def test_initial_state_is_idle():
    c = _ctrl()
    assert c.state == MegapackState.IDLE


def test_idle_to_discharging():
    c = _ctrl()
    snap = c.tick(grid_utilisation_pct=92.0)
    assert c.state == MegapackState.DISCHARGING


def test_idle_to_charging():
    c = _ctrl()
    # Pre-set SoC below 95% (default is 80%)
    snap = c.tick(grid_utilisation_pct=55.0)  # underloaded
    assert c.state == MegapackState.CHARGING


def test_discharging_to_idle_with_hysteresis():
    c = _ctrl()
    c.tick(grid_utilisation_pct=92.0)   # enter DISCHARGING
    assert c.state == MegapackState.DISCHARGING
    # Grid must drop below threshold - 5% = 85% to return to IDLE
    c.tick(grid_utilisation_pct=88.0)   # still above 85% — stays DISCHARGING
    assert c.state == MegapackState.DISCHARGING
    c.tick(grid_utilisation_pct=83.0)   # below 85% — back to IDLE
    assert c.state == MegapackState.IDLE


def test_discharging_to_fault_on_critical_soc():
    dispatch = MagicMock()
    c = _ctrl(dispatch=dispatch)
    c.tick(grid_utilisation_pct=92.0)           # enter DISCHARGING
    c._model.soc_pct = CRITICAL_SOC_PCT - 0.1   # force critical SoC
    snap = c.tick(grid_utilisation_pct=92.0)
    assert c.state == MegapackState.FAULT
    dispatch.assert_called()
    assert dispatch.call_args[0][0] == "megapack_fault"


def test_charging_to_idle_at_95pct():
    c = _ctrl()
    c.tick(grid_utilisation_pct=55.0)   # enter CHARGING
    c._model.soc_pct = 94.9
    c.tick(grid_utilisation_pct=55.0)   # still below 95 — stays CHARGING
    assert c.state == MegapackState.CHARGING
    c._model.soc_pct = 95.1
    c.tick(grid_utilisation_pct=55.0)   # hits 95% — back to IDLE
    assert c.state == MegapackState.IDLE


def test_fault_is_sticky():
    c = _ctrl()
    c.tick(grid_utilisation_pct=92.0)
    c._model.soc_pct = CRITICAL_SOC_PCT - 0.1
    c.tick(grid_utilisation_pct=92.0)   # enter FAULT
    assert c.state == MegapackState.FAULT
    c.tick(grid_utilisation_pct=50.0)   # normal grid — fault persists
    assert c.state == MegapackState.FAULT


def test_manual_reset_clears_fault():
    c = _ctrl()
    c.tick(grid_utilisation_pct=92.0)
    c._model.soc_pct = CRITICAL_SOC_PCT - 0.1
    c.tick(grid_utilisation_pct=92.0)
    assert c.state == MegapackState.FAULT
    c.manual_reset(operator_id="test-operator")
    assert c.state == MegapackState.IDLE


def test_hardware_fault_triggers_fault_state():
    dispatch = MagicMock()
    c = _ctrl(dispatch=dispatch)
    snap = c.tick(grid_utilisation_pct=70.0, hardware_fault=True)
    assert c.state == MegapackState.FAULT
    dispatch.assert_called()
