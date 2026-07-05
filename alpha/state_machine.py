# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
"""
Megapack Charge/Discharge State Machine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Deterministic state machine managing Megapack battery transitions
with grid failover, SOC tracking, and transition guards.

States: IDLE → CHARGING → DISCHARGING → FREQUENCY_RESPONSE → FAILOVER → EMERGENCY_SHED
"""

import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable, List
from datetime import datetime

logger = logging.getLogger("MegapackStateMachine")


class MegapackState(Enum):
    IDLE = "idle"
    CHARGING = "charging"
    DISCHARGING = "discharging"
    FREQUENCY_RESPONSE = "frequency_response"
    GRID_FAILOVER = "grid_failover"
    EMERGENCY_SHED = "emergency_shed"
    MAINTENANCE = "maintenance"
    FAULT = "fault"


class TransitionEvent(Enum):
    GRID_CONNECTED = "grid_connected"
    GRID_FAILED = "grid_failed"
    DEMAND_EXCEEDS_SUPPLY = "demand_exceeds_supply"
    DEMAND_NORMALIZED = "demand_normalized"
    SOC_LOW = "soc_low"
    SOC_CRITICAL = "soc_critical"
    SOC_RECOVERED = "soc_recovered"
    FREQUENCY_DEVIATION = "frequency_deviation"
    FREQUENCY_STABLE = "frequency_stable"
    MAINTENANCE_REQUESTED = "maintenance_requested"
    FAULT_DETECTED = "fault_detected"
    FAULT_CLEARED = "fault_cleared"
    EMERGENCY_OVERLOAD = "emergency_overload"


@dataclass(frozen=True)
class TransitionGuard:
    name: str
    check: Callable[["MegapackContext"], bool]
    reason_on_fail: str


@dataclass
class Transition:
    from_state: MegapackState
    to_state: MegapackState
    event: TransitionEvent
    guards: List[TransitionGuard] = field(default_factory=list)
    on_enter: Optional[Callable[["MegapackContext"], None]] = None
    on_exit: Optional[Callable[["MegapackContext"], None]] = None


@dataclass
class MegapackContext:
    soc_pct: float
    grid_online: bool
    grid_frequency_hz: float
    current_power_mw: float
    max_discharge_mw: float
    max_charge_mw: float
    capacity_mwh: float
    fault_code: Optional[str] = None
    last_transition_time: float = field(default_factory=time.time)
    transition_count: int = 0
    alarm_log: List[str] = field(default_factory=list)

    @property
    def available_energy_mwh(self) -> float:
        return self.capacity_mwh * (self.soc_pct / 100.0) * 0.923

    @property
    def available_discharge_mw(self) -> float:
        if self.soc_pct < 10.0:
            return 0.0
        return min(self.max_discharge_mw, self.available_energy_mwh * 6)

    def log_alarm(self, message: str):
        ts = datetime.now().isoformat()
        self.alarm_log.append(f"[{ts}] {message}")
        logger.warning(f"ALARM: {message}")


def _guard_soc_above_threshold(ctx: MegapackContext) -> bool:
    return ctx.soc_pct > 10.0


def _guard_grid_online(ctx: MegapackContext) -> bool:
    return ctx.grid_online


def _guard_grid_offline(ctx: MegapackContext) -> bool:
    return not ctx.grid_online


def _guard_frequency_deviation(ctx: MegapackContext) -> bool:
    return abs(ctx.grid_frequency_hz - 60.0) > 0.05


def _guard_frequency_stable(ctx: MegapackContext) -> bool:
    return abs(ctx.grid_frequency_hz - 60.0) <= 0.05


def _guard_soc_recovered(ctx: MegapackContext) -> bool:
    return ctx.soc_pct >= 30.0


def _guard_soc_critical(ctx: MegapackContext) -> bool:
    return ctx.soc_pct < 15.0


def _guard_no_fault(ctx: MegapackContext) -> bool:
    return ctx.fault_code is None


class MegapackStateMachine:
    def __init__(self):
        self.state = MegapackState.IDLE
        self.ctx = MegapackContext(
            soc_pct=80.0,
            grid_online=True,
            grid_frequency_hz=60.0,
            current_power_mw=0.0,
            max_discharge_mw=2500.0,
            max_charge_mw=1250.0,
            capacity_mwh=2000.0,
        )
        self._transitions: List[Transition] = self._build_transitions()
        self._transition_map: Dict[tuple, Transition] = {}
        for t in self._transitions:
            key = (t.from_state, t.event)
            self._transition_map[key] = t
        logger.info(
            f"MegapackStateMachine initialized: state={self.state.value}, "
            f"soc={self.ctx.soc_pct}%, capacity={self.ctx.capacity_mwh}MWh"
        )

    def _build_transitions(self) -> List[Transition]:
        return [
            Transition(
                from_state=MegapackState.IDLE,
                to_state=MegapackState.CHARGING,
                event=TransitionEvent.GRID_CONNECTED,
                guards=[
                    TransitionGuard("soc_below_95", lambda ctx: ctx.soc_pct < 95.0, "SOC at or above 95%"),
                    TransitionGuard("grid_online", _guard_grid_online, "Grid is offline"),
                ],
            ),
            Transition(
                from_state=MegapackState.IDLE,
                to_state=MegapackState.DISCHARGING,
                event=TransitionEvent.DEMAND_EXCEEDS_SUPPLY,
                guards=[
                    TransitionGuard("soc_above_10", _guard_soc_above_threshold, "SOC below 10%"),
                    TransitionGuard("grid_online", _guard_grid_online, "Grid is offline"),
                ],
            ),
            Transition(
                from_state=MegapackState.IDLE,
                to_state=MegapackState.FREQUENCY_RESPONSE,
                event=TransitionEvent.FREQUENCY_DEVIATION,
                guards=[
                    TransitionGuard("soc_above_10", _guard_soc_above_threshold, "SOC below 10%"),
                    TransitionGuard("frequency_deviation", _guard_frequency_deviation, "Frequency within tolerance"),
                    TransitionGuard("no_fault", _guard_no_fault, "Active fault present"),
                ],
            ),
            Transition(
                from_state=MegapackState.IDLE,
                to_state=MegapackState.GRID_FAILOVER,
                event=TransitionEvent.GRID_FAILED,
                guards=[
                    TransitionGuard("soc_above_10", _guard_soc_above_threshold, "SOC below 10%"),
                    TransitionGuard("grid_offline", _guard_grid_offline, "Grid is still online"),
                    TransitionGuard("no_fault", _guard_no_fault, "Active fault present"),
                ],
            ),
            Transition(
                from_state=MegapackState.IDLE,
                to_state=MegapackState.EMERGENCY_SHED,
                event=TransitionEvent.EMERGENCY_OVERLOAD,
                guards=[
                    TransitionGuard("soc_above_5", lambda ctx: ctx.soc_pct > 5.0, "SOC below 5%"),
                ],
            ),
            Transition(
                from_state=MegapackState.CHARGING,
                to_state=MegapackState.IDLE,
                event=TransitionEvent.SOC_RECOVERED,
                guards=[TransitionGuard("soc_at_95", lambda ctx: ctx.soc_pct >= 95.0, "SOC below 95%")],
            ),
            Transition(
                from_state=MegapackState.CHARGING,
                to_state=MegapackState.IDLE,
                event=TransitionEvent.GRID_FAILED,
                guards=[TransitionGuard("grid_offline", _guard_grid_offline, "Grid is still online")],
            ),
            Transition(
                from_state=MegapackState.DISCHARGING,
                to_state=MegapackState.IDLE,
                event=TransitionEvent.DEMAND_NORMALIZED,
                guards=[],
            ),
            Transition(
                from_state=MegapackState.DISCHARGING,
                to_state=MegapackState.IDLE,
                event=TransitionEvent.SOC_LOW,
                guards=[TransitionGuard("soc_below_10", lambda ctx: ctx.soc_pct < 10.0, "SOC still above 10%")],
            ),
            Transition(
                from_state=MegapackState.DISCHARGING,
                to_state=MegapackState.FREQUENCY_RESPONSE,
                event=TransitionEvent.FREQUENCY_DEVIATION,
                guards=[TransitionGuard("frequency_deviation", _guard_frequency_deviation, "Frequency within tolerance")],
            ),
            Transition(
                from_state=MegapackState.DISCHARGING,
                to_state=MegapackState.GRID_FAILOVER,
                event=TransitionEvent.GRID_FAILED,
                guards=[TransitionGuard("grid_offline", _guard_grid_offline, "Grid is still online")],
            ),
            Transition(
                from_state=MegapackState.FREQUENCY_RESPONSE,
                to_state=MegapackState.IDLE,
                event=TransitionEvent.FREQUENCY_STABLE,
                guards=[TransitionGuard("frequency_stable", _guard_frequency_stable, "Frequency still deviated")],
            ),
            Transition(
                from_state=MegapackState.FREQUENCY_RESPONSE,
                to_state=MegapackState.IDLE,
                event=TransitionEvent.SOC_LOW,
                guards=[TransitionGuard("soc_below_10", lambda ctx: ctx.soc_pct < 10.0, "SOC still above 10%")],
            ),
            Transition(
                from_state=MegapackState.GRID_FAILOVER,
                to_state=MegapackState.IDLE,
                event=TransitionEvent.GRID_CONNECTED,
                guards=[TransitionGuard("grid_online", _guard_grid_online, "Grid is offline")],
            ),
            Transition(
                from_state=MegapackState.GRID_FAILOVER,
                to_state=MegapackState.EMERGENCY_SHED,
                event=TransitionEvent.SOC_CRITICAL,
                guards=[TransitionGuard("soc_critical", _guard_soc_critical, "SOC still above 15%")],
            ),
            Transition(
                from_state=MegapackState.EMERGENCY_SHED,
                to_state=MegapackState.GRID_FAILOVER,
                event=TransitionEvent.SOC_RECOVERED,
                guards=[TransitionGuard("soc_recovered", _guard_soc_recovered, "SOC below 30%")],
            ),
            Transition(
                from_state=MegapackState.EMERGENCY_SHED,
                to_state=MegapackState.IDLE,
                event=TransitionEvent.GRID_CONNECTED,
                guards=[TransitionGuard("grid_online", _guard_grid_online, "Grid is offline")],
            ),
            Transition(
                from_state=MegapackState.MAINTENANCE,
                to_state=MegapackState.IDLE,
                event=TransitionEvent.FAULT_CLEARED,
                guards=[TransitionGuard("no_fault", _guard_no_fault, "Active fault present")],
            ),
            Transition(
                from_state=MegapackState.FAULT,
                to_state=MegapackState.MAINTENANCE,
                event=TransitionEvent.FAULT_CLEARED,
                guards=[TransitionGuard("no_fault", _guard_no_fault, "Active fault present")],
            ),
        ]

    def _evaluate_guards(self, transition: Transition) -> tuple[bool, Optional[str]]:
        for guard in transition.guards:
            if not guard.check(self.ctx):
                return False, guard.reason_on_fail
        return True, None

    def process_event(self, event: TransitionEvent) -> tuple[bool, Optional[MegapackState], Optional[str]]:
        key = (self.state, event)
        transition = self._transition_map.get(key)
        if transition is None:
            logger.debug(f"No transition for state={self.state.value}, event={event.value}")
            return False, None, f"No transition defined for {self.state.value} + {event.value}"

        passed, fail_reason = self._evaluate_guards(transition)
        if not passed:
            logger.warning(
                f"Guard blocked transition {self.state.value} → {transition.to_state.value}: {fail_reason}"
            )
            return False, None, fail_reason

        if transition.on_exit:
            transition.on_exit(self.ctx)

        old_state = self.state
        self.state = transition.to_state
        self.ctx.last_transition_time = time.time()
        self.ctx.transition_count += 1

        if transition.on_enter:
            transition.on_enter(self.ctx)

        logger.info(
            f"Transition: {old_state.value} → {self.state.value} (event={event.value}, "
            f"soc={self.ctx.soc_pct:.1f}%, transitions={self.ctx.transition_count})"
        )
        return True, self.state, None

    def update_soc(self, power_mw: float, interval_hours: float) -> float:
        energy_delta_mwh = power_mw * interval_hours
        self.ctx.soc_pct -= (energy_delta_mwh / self.ctx.capacity_mwh) * 100
        self.ctx.soc_pct = max(0.0, min(100.0, self.ctx.soc_pct))

        if self.ctx.soc_pct < 10.0:
            self.ctx.log_alarm(f"SOC critically low: {self.ctx.soc_pct:.1f}%")
            self.process_event(TransitionEvent.SOC_LOW)
        elif self.ctx.soc_pct < 15.0:
            self.process_event(TransitionEvent.SOC_CRITICAL)

        return self.ctx.soc_pct

    def inject_fault(self, fault_code: str) -> None:
        self.ctx.fault_code = fault_code
        self.ctx.log_alarm(f"Fault injected: {fault_code}")
        self.process_event(TransitionEvent.FAULT_DETECTED)

    def clear_fault(self) -> None:
        self.ctx.fault_code = None
        self.process_event(TransitionEvent.FAULT_CLEARED)

    def get_telemetry(self) -> Dict:
        return {
            "state": self.state.value,
            "soc_pct": round(self.ctx.soc_pct, 2),
            "grid_online": self.ctx.grid_online,
            "grid_frequency_hz": self.ctx.grid_frequency_hz,
            "current_power_mw": self.ctx.current_power_mw,
            "available_discharge_mw": round(self.ctx.available_discharge_mw, 2),
            "available_energy_mwh": round(self.ctx.available_energy_mwh, 2),
            "transition_count": self.ctx.transition_count,
            "fault_code": self.ctx.fault_code,
            "timestamp": datetime.now().isoformat(),
        }


if __name__ == "__main__":
    sm = MegapackStateMachine()
    print(f"Initial state: {sm.state.value}")

    sm.ctx.grid_frequency_hz = 59.85
    ok, new_state, err = sm.process_event(TransitionEvent.FREQUENCY_DEVIATION)
    print(f"Freq deviation: ok={ok}, state={sm.state.value}")

    sm.ctx.current_power_mw = 800.0
    sm.update_soc(800.0, 0.01)
    print(f"SOC after discharge: {sm.ctx.soc_pct:.1f}%")

    sm.ctx.grid_online = False
    ok, new_state, err = sm.process_event(TransitionEvent.GRID_FAILED)
    print(f"Grid failover: ok={ok}, state={sm.state.value}")

    print(f"\nTelemetry: {sm.get_telemetry()}")
