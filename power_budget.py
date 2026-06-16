"""power_budget.py — GW-scale power budget model (Issue #3)

Tracks real-time load across Colossus grid segments:
  - utility grid
  - supplemental gas turbine
  - renewable (solar)

State persists to Supabase `energy_budget` table.
MCP ALERT fires when any segment exceeds 90% capacity.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("ColossusEnergyBalancer.PowerBudget")

ALERT_THRESHOLD_PCT = 90.0  # emit MCP alert above this utilisation


@dataclass
class GridSegment:
    """One logical grid segment (utility feed, gas turbine bank, solar array)."""
    segment_id: str
    source_type: str          # 'utility' | 'gas' | 'renewable'
    capacity_mw: float
    current_load_mw: float = 0.0

    @property
    def headroom_mw(self) -> float:
        return max(0.0, self.capacity_mw - self.current_load_mw)

    @property
    def utilisation_pct(self) -> float:
        if self.capacity_mw <= 0:
            return 0.0
        return (self.current_load_mw / self.capacity_mw) * 100.0

    def to_row(self) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "segment_id": self.segment_id,
            "source_type": self.source_type,
            "capacity_mw": self.capacity_mw,
            "current_load_mw": self.current_load_mw,
            "headroom_mw": self.headroom_mw,
            "utilisation_pct": round(self.utilisation_pct, 2),
            "ts": time.time(),
        }


class PowerBudgetModel:
    """Tracks all grid segments and persists state to Supabase.

    Usage
    -----
    model = PowerBudgetModel(sb_client)
    model.update_segment('utility-a', current_load_mw=820)
    model.tick()   # upserts all segments, fires alerts
    """

    def __init__(self, sb=None, mcp_dispatch=None):
        """
        sb:           Supabase client (or None for unit tests with mock)
        mcp_dispatch: callable(event_type, payload) for MCP alerts
        """
        self._sb = sb
        self._mcp_dispatch = mcp_dispatch or self._default_mcp_log
        self._segments: Dict[str, GridSegment] = {}
        self._tick_count = 0

    # ------------------------------------------------------------------
    # Segment management
    # ------------------------------------------------------------------

    def register_segment(self, seg: GridSegment) -> None:
        self._segments[seg.segment_id] = seg

    def update_segment(self, segment_id: str, current_load_mw: float) -> None:
        if segment_id in self._segments:
            self._segments[segment_id].current_load_mw = current_load_mw
        else:
            logger.warning("update_segment: unknown segment '%s'", segment_id)

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick(self) -> List[dict]:
        """Update all segments, write to Supabase, emit alerts.

        Returns list of row dicts that were upserted.
        """
        self._tick_count += 1
        rows = []
        for seg in self._segments.values():
            row = seg.to_row()
            rows.append(row)
            if seg.utilisation_pct > ALERT_THRESHOLD_PCT:
                self._mcp_dispatch("budget_breach", {
                    "segment_id": seg.segment_id,
                    "source_type": seg.source_type,
                    "utilisation_pct": round(seg.utilisation_pct, 1),
                    "headroom_mw": round(seg.headroom_mw, 2),
                })
                logger.warning(
                    "BUDGET BREACH: segment %s at %.1f%% capacity",
                    seg.segment_id, seg.utilisation_pct,
                )

        if self._sb is not None:
            try:
                self._sb.table("energy_budget").upsert(rows).execute()
            except Exception as exc:
                logger.error("PowerBudgetModel Supabase upsert failed: %s", exc)

        return rows

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def total_load_mw(self) -> float:
        return sum(s.current_load_mw for s in self._segments.values())

    @property
    def total_capacity_mw(self) -> float:
        return sum(s.capacity_mw for s in self._segments.values())

    def segments(self) -> Dict[str, GridSegment]:
        return dict(self._segments)

    @staticmethod
    def _default_mcp_log(event_type: str, payload: dict) -> None:
        logger.info("MCP_DISPATCH [%s]: %s", event_type, payload)
