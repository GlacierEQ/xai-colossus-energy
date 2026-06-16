"""megapack_buffer/megapack_state_machine.py — Megapack FSM (Issue #6)

Formal finite-state machine for the 560 MWh / 140 MW Megapack buffer.
Enforces valid state transitions, SoC guard conditions, and writes
events to Supabase megapack_events table when a client is available.

State graph
-----------
    IDLE → CHARGING           (SoC < 95%, solar surplus available)
    IDLE → DISCHARGING        (grid demand > soft limit)
    IDLE → FREQUENCY_RESPONSE (|grid_freq - 60| > 0.05 Hz)
    IDLE → RESERVE             (operator manual hold)

    CHARGING → IDLE            (SoC ≥ 95% or no surplus)
    DISCHARGING → IDLE         (SoC ≤ 10% or demand normalised)
    FREQUENCY_RESPONSE → IDLE  (frequency within 0.05 Hz of 60)
    RESERVE → IDLE              (operator release)

    Any state → IDLE is always valid (emergency stop).

Invalid transitions (e.g. CHARGING → DISCHARGING directly) raise
MegapackTransitionError so silent mode corruption is impossible.
"""

import logging
import time
import uuid
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("MegapackFSM")


class MegapackState(Enum):
    IDLE               = "idle"
    CHARGING           = "charging"
    DISCHARGING        = "discharging"
    FREQUENCY_RESPONSE = "frequency_response"
    RESERVE            = "reserve"


# Valid transitions: {from_state: {to_states}}
_VALID_TRANSITIONS: Dict[MegapackState, set] = {
    MegapackState.IDLE:               {
        MegapackState.CHARGING,
        MegapackState.DISCHARGING,
        MegapackState.FREQUENCY_RESPONSE,
        MegapackState.RESERVE,
    },
    MegapackState.CHARGING:           {MegapackState.IDLE},
    MegapackState.DISCHARGING:        {MegapackState.IDLE},
    MegapackState.FREQUENCY_RESPONSE: {MegapackState.IDLE},
    MegapackState.RESERVE:            {MegapackState.IDLE},
}

# SoC guard constants
SOC_MIN_DISCHARGE = 10.0   # % — do not discharge below this
SOC_MAX_CHARGE    = 95.0   # % — stop charging above this
CAPACITY_MWH      = 560.0
MAX_DISCHARGE_MW  = 140.0
MAX_CHARGE_MW     = 70.0


class MegapackTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""


class MegapackStateMachine:
    """
    Formal FSM for the Colossus Megapack buffer.

    Parameters
    ----------
    soc_pct : float
        Initial state-of-charge as a percentage (0–100).
    sb : optional
        Supabase client. If None, events are only logged (no DB write).
    """

    def __init__(self, soc_pct: float = 80.0, sb=None):
        self.state: MegapackState = MegapackState.IDLE
        self.soc_pct: float = max(0.0, min(100.0, soc_pct))
        self.current_power_mw: float = 0.0
        self._sb = sb
        self._event_log: List[Dict] = []
        logger.info(
            "MegapackFSM initialised: state=IDLE soc=%.1f%%", self.soc_pct
        )

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def available_discharge_mw(self) -> float:
        """Maximum discharge power respecting SoC guard."""
        if self.soc_pct <= SOC_MIN_DISCHARGE:
            return 0.0
        available_energy = CAPACITY_MWH * (self.soc_pct / 100.0) * 0.923
        return min(MAX_DISCHARGE_MW, available_energy * 6)

    @property
    def can_charge(self) -> bool:
        return self.soc_pct < SOC_MAX_CHARGE

    @property
    def can_discharge(self) -> bool:
        return self.soc_pct > SOC_MIN_DISCHARGE

    @property
    def event_log(self) -> List[Dict]:
        return list(self._event_log)

    # ------------------------------------------------------------------
    # Transition engine
    # ------------------------------------------------------------------

    def _transition(self, new_state: MegapackState, reason: str, power_mw: float = 0.0) -> None:
        """Execute a validated state transition.

        Raises MegapackTransitionError if the transition is not in the
        valid transition graph.
        """
        allowed = _VALID_TRANSITIONS.get(self.state, set())
        if new_state not in allowed and new_state != self.state:
            raise MegapackTransitionError(
                f"Invalid transition: {self.state.value} → {new_state.value} "
                f"(reason: {reason})"
            )
        old_state = self.state
        self.state = new_state
        self.current_power_mw = power_mw
        event = {
            "id":         str(uuid.uuid4()),
            "ts":         time.time(),
            "from_state": old_state.value,
            "to_state":   new_state.value,
            "reason":     reason,
            "power_mw":   round(power_mw, 3),
            "soc_pct":    round(self.soc_pct, 2),
        }
        self._event_log.append(event)
        logger.info(
            "Megapack FSM: %s → %s | %.1f MW | SoC %.1f%% | %s",
            old_state.value, new_state.value, power_mw, self.soc_pct, reason,
        )
        self._write_event(event)

    def _write_event(self, event: Dict) -> None:
        if self._sb is None:
            return
        try:
            self._sb.table("megapack_events").insert(event).execute()
        except Exception as exc:
            logger.error("megapack_events Supabase write failed: %s", exc)

    # ------------------------------------------------------------------
    # Public commands
    # ------------------------------------------------------------------

    def start_charging(self, solar_surplus_mw: float) -> float:
        """Transition IDLE → CHARGING. Returns actual charge rate MW.

        Guards: must be IDLE, SoC < 95%, surplus > 0.
        """
        if not self.can_charge:
            logger.info("Charging skipped: SoC %.1f%% already at cap", self.soc_pct)
            return 0.0
        absorb = min(solar_surplus_mw, MAX_CHARGE_MW)
        self._transition(
            MegapackState.CHARGING,
            f"solar_surplus={solar_surplus_mw:.1f}MW",
            power_mw=-absorb,   # negative = drawing power in
        )
        return absorb

    def start_discharging(self, demand_excess_mw: float) -> float:
        """Transition IDLE → DISCHARGING. Returns actual dispatch MW.

        Guards: must be IDLE, SoC > 10%.
        """
        if not self.can_discharge:
            logger.warning(
                "Discharge blocked: SoC %.1f%% ≤ %.1f%% floor",
                self.soc_pct, SOC_MIN_DISCHARGE,
            )
            return 0.0
        dispatch = min(demand_excess_mw, self.available_discharge_mw)
        self._transition(
            MegapackState.DISCHARGING,
            f"demand_excess={demand_excess_mw:.1f}MW",
            power_mw=dispatch,
        )
        return dispatch

    def start_frequency_response(self, freq_hz: float) -> float:
        """Transition IDLE → FREQUENCY_RESPONSE. Returns response power MW.

        Positive return = discharging (under-freq), negative = charging (over-freq).
        """
        deviation = 60.0 - freq_hz
        if abs(deviation) < 0.05:
            return 0.0
        response_mw = min(50.0, abs(deviation) * 250)
        if deviation > 0:
            actual = min(response_mw, self.available_discharge_mw)
            self._transition(
                MegapackState.FREQUENCY_RESPONSE,
                f"under_freq={freq_hz:.3f}Hz",
                power_mw=actual,
            )
            return actual
        else:
            actual = min(response_mw, MAX_CHARGE_MW)
            self._transition(
                MegapackState.FREQUENCY_RESPONSE,
                f"over_freq={freq_hz:.3f}Hz",
                power_mw=-actual,
            )
            return -actual

    def enter_reserve(self) -> None:
        """Transition IDLE → RESERVE (operator manual hold)."""
        self._transition(MegapackState.RESERVE, "operator_manual_hold", power_mw=0.0)

    def return_to_idle(self, reason: str = "nominal") -> None:
        """Transition any state → IDLE (always valid — emergency stop path)."""
        self.state = MegapackState.IDLE  # bypass graph for emergency stop
        self.current_power_mw = 0.0
        event = {
            "id":       str(uuid.uuid4()),
            "ts":       time.time(),
            "from_state": self.state.value,
            "to_state": MegapackState.IDLE.value,
            "reason":   reason,
            "power_mw": 0.0,
            "soc_pct":  round(self.soc_pct, 2),
        }
        self._event_log.append(event)
        logger.info("Megapack FSM: → IDLE | reason=%s", reason)
        self._write_event(event)

    def update_soc(self, interval_hours: float) -> None:
        """Update SoC based on current_power_mw over interval_hours.

        Positive power_mw = discharging (SoC decreases).
        Negative power_mw = charging (SoC increases).
        """
        energy_delta_mwh = self.current_power_mw * interval_hours
        self.soc_pct -= (energy_delta_mwh / CAPACITY_MWH) * 100
        self.soc_pct = max(0.0, min(100.0, self.soc_pct))
        # Auto-return to IDLE on SoC guard hits
        if self.state == MegapackState.DISCHARGING and self.soc_pct <= SOC_MIN_DISCHARGE:
            self.return_to_idle(reason="soc_floor_reached")
        elif self.state == MegapackState.CHARGING and self.soc_pct >= SOC_MAX_CHARGE:
            self.return_to_idle(reason="soc_cap_reached")
