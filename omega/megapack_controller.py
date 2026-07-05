# Omega (How) — Controllers | Alpha (What) — Pure Physics | 1337.
"""megapack_buffer/megapack_controller.py — Megapack state machine (Issue #6)

Four explicit states: IDLE, CHARGING, DISCHARGING, FAULT.
Transitions driven by grid signal from xai_energy_balancer.py.
FAULT entry emits MCP event.

This controller wraps MegapackModel and adds explicit FAULT handling.
"""

import logging
import time
import uuid
from enum import Enum
from typing import Optional, Callable

# Fixed: was `from megapack_model import ...` which fails unless CWD is megapack_buffer/
# Now uses the fully-qualified package path, importable from anywhere on PYTHONPATH.
from megapack_buffer.megapack_model import MegapackModel, MegapackConfig, CRITICAL_SOC_PCT

logger = logging.getLogger("ColossusEnergyBalancer.MegapackController")


class MegapackState(str, Enum):
    IDLE        = "IDLE"
    CHARGING    = "CHARGING"
    DISCHARGING = "DISCHARGING"
    FAULT       = "FAULT"


# Grid utilisation thresholds (configurable at init)
DISCHARGE_THRESHOLD_PCT = 90.0   # grid overload → discharge
CHARGE_THRESHOLD_PCT    = 60.0   # grid underloaded → charge


class MegapackController:
    """State machine wrapper around MegapackModel.

    States
    ------
    IDLE        No active charge or discharge.  Waiting.
    CHARGING    Grid is underloaded; Megapack absorbing excess capacity.
    DISCHARGING Grid is overloaded; Megapack supplying demand.
    FAULT       SoC critical OR hardware fault flag.  No dispatch allowed.

    Transitions
    -----------
    IDLE → DISCHARGING   grid_util >= discharge_threshold AND soc > critical
    IDLE → CHARGING      grid_util <= charge_threshold AND soc < 95%
    DISCHARGING → IDLE   grid_util returns below discharge_threshold - 5% (hysteresis)
    DISCHARGING → FAULT  soc drops to critical_soc_pct
    CHARGING → IDLE      soc >= 95%
    CHARGING → FAULT     hardware_fault flag set
    FAULT → IDLE         manual_reset() called by operator
    """

    def __init__(
        self,
        config: Optional[MegapackConfig] = None,
        sb=None,
        mcp_dispatch: Optional[Callable] = None,
        discharge_threshold_pct: float = DISCHARGE_THRESHOLD_PCT,
        charge_threshold_pct: float = CHARGE_THRESHOLD_PCT,
    ):
        self.config = config or MegapackConfig()
        self._model = MegapackModel(config=self.config, sb=sb, mcp_dispatch=mcp_dispatch)
        self._sb = sb
        self._mcp_dispatch = mcp_dispatch or self._default_mcp_log
        self.discharge_threshold_pct = discharge_threshold_pct
        self.charge_threshold_pct = charge_threshold_pct
        self.state: MegapackState = MegapackState.IDLE
        self._fault_reason: Optional[str] = None
        self._tick: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tick(
        self,
        grid_utilisation_pct: float,
        hardware_fault: bool = False,
        interval_hours: float = 1 / 3600,
    ) -> dict:
        """Advance one control tick and return state snapshot."""
        self._tick += 1

        # FAULT is a sticky state — only manual_reset() clears it
        if self.state == MegapackState.FAULT:
            return self._snapshot(extra={"fault_reason": self._fault_reason})

        # Hardware fault injection
        if hardware_fault:
            return self._enter_fault("hardware_fault_signal", grid_utilisation_pct)

        soc = self._model.soc_pct

        # --- State machine transitions ---
        if self.state == MegapackState.IDLE:
            if grid_utilisation_pct >= self.discharge_threshold_pct and soc > CRITICAL_SOC_PCT:
                self._transition(MegapackState.DISCHARGING)
            elif grid_utilisation_pct <= self.charge_threshold_pct and soc < 95.0:
                self._transition(MegapackState.CHARGING)

        elif self.state == MegapackState.DISCHARGING:
            # Hysteresis: stop discharging only when load drops 5% below threshold
            if grid_utilisation_pct < self.discharge_threshold_pct - 5.0:
                self._transition(MegapackState.IDLE)
            elif soc <= CRITICAL_SOC_PCT:
                return self._enter_fault("critical_soc", grid_utilisation_pct)

        elif self.state == MegapackState.CHARGING:
            if soc >= 95.0:
                self._transition(MegapackState.IDLE)

        # Delegate physics to MegapackModel
        grid_restored = (self.state == MegapackState.CHARGING)
        self._model.tick(
            grid_utilisation_pct=grid_utilisation_pct,
            grid_restored=grid_restored,
            interval_hours=interval_hours,
        )

        return self._snapshot()

    def manual_reset(self, operator_id: str = "operator") -> None:
        """Clear FAULT state — requires human operator action."""
        if self.state == MegapackState.FAULT:
            logger.warning(
                "Megapack FAULT cleared by %s (was: %s)",
                operator_id, self._fault_reason,
            )
            self._fault_reason = None
            self._transition(MegapackState.IDLE)

    @property
    def soc_pct(self) -> float:
        return self._model.soc_pct

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _transition(self, new_state: MegapackState) -> None:
        logger.info(
            "Megapack state %s → %s (tick=%d, soc=%.1f%%)",
            self.state.value, new_state.value, self._tick, self._model.soc_pct,
        )
        self.state = new_state

    def _enter_fault(self, reason: str, grid_util: float) -> dict:
        self._fault_reason = reason
        self._transition(MegapackState.FAULT)
        self._mcp_dispatch("megapack_fault", {
            "reason": reason,
            "soc_pct": round(self._model.soc_pct, 2),
            "grid_utilisation_pct": grid_util,
            "tick": self._tick,
        })
        logger.error("Megapack FAULT: %s (soc=%.1f%%)", reason, self._model.soc_pct)
        return self._snapshot(extra={"fault_reason": reason})

    def _snapshot(self, extra: Optional[dict] = None) -> dict:
        snap = {
            "tick": self._tick,
            "state": self.state.value,
            "soc_pct": round(self._model.soc_pct, 2),
        }
        if extra:
            snap.update(extra)
        return snap

    @staticmethod
    def _default_mcp_log(event_type: str, payload: dict) -> None:
        logger.info("MCP_DISPATCH [%s]: %s", event_type, payload)
