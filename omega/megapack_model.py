"""megapack_buffer/megapack_model.py — Tesla Megapack SoC + failover model (Issue #2)

Models the 560 MWh / 140 MW Megapack buffer integrated with Colossus.

Events emitted to Supabase audit_events:
  MEGAPACK_DISCHARGE_START   — grid drop triggers autonomous discharge
  MEGAPACK_RECHARGE_COMPLETE — SoC returns to >= 95%
  MEGAPACK_CRITICAL_SOC      — SoC drops below 15%

Gauntlet: inject grid drop at tick 5, assert discharge starts by tick 6.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable

logger = logging.getLogger("ColossusEnergyBalancer.MegapackModel")

# Colossus Megapack constants (from xai_energy_balancer.py)
DEFAULT_CAPACITY_MWH = 560.0
DEFAULT_MAX_DISCHARGE_MW = 140.0
DEFAULT_MAX_CHARGE_MW = 70.0
DEFAULT_FAILOVER_THRESHOLD_PCT = 90.0   # grid utilisation % that triggers discharge
CRITICAL_SOC_PCT = 15.0
RECHARGE_TARGET_PCT = 95.0


class MegapackEvent(str, Enum):
    DISCHARGE_START     = "MEGAPACK_DISCHARGE_START"
    RECHARGE_COMPLETE   = "MEGAPACK_RECHARGE_COMPLETE"
    CRITICAL_SOC        = "MEGAPACK_CRITICAL_SOC"


@dataclass
class MegapackConfig:
    capacity_mwh: float = DEFAULT_CAPACITY_MWH
    max_discharge_mw: float = DEFAULT_MAX_DISCHARGE_MW
    max_charge_mw: float = DEFAULT_MAX_CHARGE_MW
    failover_threshold_pct: float = DEFAULT_FAILOVER_THRESHOLD_PCT
    initial_soc_pct: float = 80.0


class MegapackModel:
    """State-of-charge tracker with grid failover and Supabase event emission.

    Usage
    -----
    model = MegapackModel(config, sb_client)
    model.tick(grid_utilisation_pct=92.0, grid_restored=False, interval_hours=1/3600)
    """

    def __init__(
        self,
        config: Optional[MegapackConfig] = None,
        sb=None,
        mcp_dispatch: Optional[Callable] = None,
    ):
        self.config = config or MegapackConfig()
        self._sb = sb
        self._mcp_dispatch = mcp_dispatch or self._default_mcp_log

        self.soc_pct: float = self.config.initial_soc_pct
        self.discharging: bool = False
        self.charging: bool = False
        self._critical_emitted: bool = False
        self._recharge_emitted: bool = False
        self._tick: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tick(
        self,
        grid_utilisation_pct: float,
        grid_restored: bool = False,
        interval_hours: float = 1 / 3600,
    ) -> dict:
        """Advance one control tick.

        Args:
            grid_utilisation_pct: Current grid load as % of capacity.
            grid_restored:        True when a previous grid drop has cleared.
            interval_hours:       Duration of this tick in hours (default 1 second).

        Returns:
            State snapshot dict.
        """
        self._tick += 1
        events_emitted = []

        # --- Failover trigger: grid overload → start discharge ---
        if grid_utilisation_pct >= self.config.failover_threshold_pct and not self.discharging:
            if self.soc_pct > CRITICAL_SOC_PCT:
                self.discharging = True
                self.charging = False
                self._recharge_emitted = False
                self._emit_event(MegapackEvent.DISCHARGE_START, {
                    "grid_utilisation_pct": grid_utilisation_pct,
                    "soc_pct": round(self.soc_pct, 2),
                    "tick": self._tick,
                })
                events_emitted.append(MegapackEvent.DISCHARGE_START)
                logger.info(
                    "Megapack DISCHARGE START — grid at %.1f%%, SoC %.1f%%",
                    grid_utilisation_pct, self.soc_pct,
                )

        # --- Recharge: grid restored and not already at target ---
        if grid_restored and not self.charging and self.soc_pct < RECHARGE_TARGET_PCT:
            self.discharging = False
            self.charging = True
            logger.info("Megapack RECHARGE START — SoC %.1f%%", self.soc_pct)

        # --- SoC integration ---
        if self.discharging:
            discharge_mwh = min(
                self.config.max_discharge_mw * interval_hours,
                self.config.capacity_mwh * (self.soc_pct / 100.0) -
                self.config.capacity_mwh * (CRITICAL_SOC_PCT / 100.0)
            )
            self.soc_pct -= (discharge_mwh / self.config.capacity_mwh) * 100.0

        if self.charging:
            charge_mwh = self.config.max_charge_mw * interval_hours
            self.soc_pct = min(100.0, self.soc_pct + (charge_mwh / self.config.capacity_mwh) * 100.0)

        self.soc_pct = max(0.0, min(100.0, self.soc_pct))

        # --- Critical SoC warning ---
        if self.soc_pct <= CRITICAL_SOC_PCT and not self._critical_emitted:
            self._critical_emitted = True
            self.discharging = False  # auto-protect
            self._emit_event(MegapackEvent.CRITICAL_SOC, {
                "soc_pct": round(self.soc_pct, 2),
                "tick": self._tick,
            })
            events_emitted.append(MegapackEvent.CRITICAL_SOC)
            logger.error("Megapack CRITICAL SOC: %.1f%%", self.soc_pct)
        elif self.soc_pct > CRITICAL_SOC_PCT:
            self._critical_emitted = False  # reset for next crossing

        # --- Recharge complete ---
        if self.charging and self.soc_pct >= RECHARGE_TARGET_PCT and not self._recharge_emitted:
            self._recharge_emitted = True
            self.charging = False
            self._emit_event(MegapackEvent.RECHARGE_COMPLETE, {
                "soc_pct": round(self.soc_pct, 2),
                "tick": self._tick,
            })
            events_emitted.append(MegapackEvent.RECHARGE_COMPLETE)
            logger.info("Megapack RECHARGE COMPLETE — SoC %.1f%%", self.soc_pct)

        return {
            "tick": self._tick,
            "soc_pct": round(self.soc_pct, 2),
            "discharging": self.discharging,
            "charging": self.charging,
            "events": [e.value for e in events_emitted],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit_event(self, event: MegapackEvent, payload: dict) -> None:
        """Write to Supabase audit_events + dispatch MCP."""
        row = {
            "id": str(uuid.uuid4()),
            "event_type": event.value,
            "payload": payload,
            "ts": time.time(),
        }
        if self._sb is not None:
            try:
                self._sb.table("audit_events").insert(row).execute()
            except Exception as exc:
                logger.error("MegapackModel Supabase write failed: %s", exc)
        self._mcp_dispatch(event.value, payload)

    @staticmethod
    def _default_mcp_log(event_type: str, payload: dict) -> None:
        logger.info("MCP_DISPATCH [%s]: %s", event_type, payload)
