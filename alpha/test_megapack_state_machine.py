# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
"""tests/test_megapack_state_machine.py — Issue #6 acceptance tests"""

import pytest
from megapack_buffer.megapack_state_machine import (
    MegapackStateMachine, MegapackState, MegapackTransitionError
)


def fsm(soc=80.0):
    return MegapackStateMachine(soc_pct=soc)


# ── Happy path transitions ───────────────────────────────────────────────────

def test_idle_to_charging():
    m = fsm(soc=50.0)
    power = m.start_charging(solar_surplus_mw=20.0)
    assert m.state == MegapackState.CHARGING
    assert power > 0


def test_idle_to_discharging():
    m = fsm(soc=80.0)
    power = m.start_discharging(demand_excess_mw=30.0)
    assert m.state == MegapackState.DISCHARGING
    assert power > 0


def test_idle_to_frequency_response_underfreq():
    m = fsm(soc=80.0)
    power = m.start_frequency_response(freq_hz=59.8)
    assert m.state == MegapackState.FREQUENCY_RESPONSE
    assert power > 0  # discharging to boost frequency


def test_idle_to_frequency_response_overfreq():
    m = fsm(soc=50.0)
    power = m.start_frequency_response(freq_hz=60.3)
    assert m.state == MegapackState.FREQUENCY_RESPONSE
    assert power < 0  # charging to absorb over-frequency


def test_charging_to_idle():
    m = fsm(soc=50.0)
    m.start_charging(10.0)
    m.return_to_idle(reason="test")
    assert m.state == MegapackState.IDLE
    assert m.current_power_mw == 0.0


def test_discharging_to_idle():
    m = fsm(soc=80.0)
    m.start_discharging(30.0)
    m.return_to_idle(reason="demand_normalised")
    assert m.state == MegapackState.IDLE


# ── Invalid transition guard ────────────────────────────────────────────────

def test_charging_to_discharging_raises():
    """CHARGING → DISCHARGING without going through IDLE must raise."""
    m = fsm(soc=50.0)
    m.start_charging(10.0)
    assert m.state == MegapackState.CHARGING
    with pytest.raises(MegapackTransitionError):
        m._transition(MegapackState.DISCHARGING, "illegal")


# ── SoC guards ─────────────────────────────────────────────────────────────

def test_discharge_blocked_at_soc_floor():
    m = fsm(soc=10.0)  # exactly at floor
    power = m.start_discharging(50.0)
    assert power == 0.0
    assert m.state == MegapackState.IDLE  # no transition


def test_charging_blocked_at_soc_cap():
    m = fsm(soc=95.0)  # at cap
    power = m.start_charging(20.0)
    assert power == 0.0
    assert m.state == MegapackState.IDLE


def test_auto_idle_on_soc_floor_during_discharge():
    """update_soc() must auto-return to IDLE when SoC hits floor mid-discharge."""
    m = fsm(soc=11.0)
    m.start_discharging(demand_excess_mw=5.0)
    # Drain past floor
    m.update_soc(interval_hours=1.0)
    assert m.state == MegapackState.IDLE
