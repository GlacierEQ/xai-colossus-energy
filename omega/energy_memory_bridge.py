# Omega (How) — Controllers | Alpha (What) — Pure Physics | 1337.
"""
EnergyMemoryBridge
==================
Thin adapter between xai-colossus-energy and the colossus-gateway MemoryRouter.

All gauntlet runs, powerflow snapshots, and APEX throttle decisions are
persisted into both Pinecone (semantic vector) and Supermemory (conversational
context) so downstream agents can ask questions like:
  "What happened when the East feeder hit 95% capacity last week?"

Environment variables (add to .env.example / Supabase secrets):
  COLOSSUS_GATEWAY_PATH  Path to the colossus-gateway repo root (default: ../colossus-gateway)
  PINECONE_API_KEY       (inherited by gateway)
  SUPERMEMORY_API_KEY    (inherited by gateway)
  ENERGY_MEMORY_ENABLED  Set to "false" to disable without breaking gauntlet runs (default: true)
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _load_gateway_router():
    """Dynamically import MemoryRouter from the colossus-gateway repo.

    Falls back gracefully if the gateway is not available so energy gauntlet
    runs never break due to a missing memory dependency.
    """
    gateway_path = Path(
        os.environ.get("COLOSSUS_GATEWAY_PATH", "../colossus-gateway")
    ).resolve()

    router_module_path = gateway_path / "src" / "memory" / "memory_router.py"
    if not router_module_path.exists():
        logger.warning(
            "colossus-gateway memory_router not found at %s — memory writes disabled.",
            router_module_path,
        )
        return None

    spec = importlib.util.spec_from_file_location(
        "colossus_gateway.memory_router", router_module_path
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore
    sys.modules["colossus_gateway.memory_router"] = module
    spec.loader.exec_module(module)  # type: ignore
    return module.MemoryRouter()


class EnergyMemoryBridge:
    """Records energy events into the shared Colossus memory layer."""

    NAMESPACE = "colossus-scenarios"
    SPACE = "colossus-scenarios"

    def __init__(self) -> None:
        self._enabled = os.environ.get("ENERGY_MEMORY_ENABLED", "true").lower() != "false"
        self._router = None
        if self._enabled:
            try:
                self._router = _load_gateway_router()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("EnergyMemoryBridge init failed: %s", exc)
                self._router = None

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def record_gauntlet_run(
        self,
        scenario_name: str,
        result: Dict[str, Any],
        passed: bool,
        tags: Optional[list] = None,
    ) -> None:
        """Persist a gauntlet run result to memory.

        Args:
            scenario_name: Human-readable scenario (e.g. "N1_east_feeder_trip")
            result:         Full result dict from the gauntlet runner
            passed:         Whether all assertions passed
            tags:           Optional extra labels (e.g. ["grid-risk", "EJ"])
        """
        if not self._router:
            return

        payload = {
            "type": "gauntlet_run",
            "repo": "xai-colossus-energy",
            "scenario": scenario_name,
            "passed": passed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tags": tags or [],
            "result_summary": self._summarise(result),
        }
        try:
            self._router.remember_scenario("energy", payload)
            logger.info("[memory] gauntlet run recorded: %s passed=%s", scenario_name, passed)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("[memory] gauntlet write failed: %s", exc)

    def record_powerflow_snapshot(
        self,
        feeder_id: str,
        mw_draw: float,
        mw_limit: float,
        headroom_mw: float,
        rack_count: int,
        water_gph: Optional[float] = None,
    ) -> None:
        """Persist a live powerflow snapshot for trend analysis.

        Call this from the energy balancer's main loop whenever a snapshot
        is emitted — every 30 s or on threshold cross is a reasonable cadence.
        """
        if not self._router:
            return

        utilisation_pct = round(mw_draw / mw_limit * 100, 2) if mw_limit else 0.0
        payload = {
            "type": "powerflow_snapshot",
            "repo": "xai-colossus-energy",
            "feeder_id": feeder_id,
            "mw_draw": mw_draw,
            "mw_limit": mw_limit,
            "headroom_mw": headroom_mw,
            "utilisation_pct": utilisation_pct,
            "rack_count": rack_count,
            "water_gph": water_gph,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alert": utilisation_pct >= 90,
        }
        try:
            self._router.remember_scenario("energy", payload)
            if utilisation_pct >= 90:
                logger.warning(
                    "[memory] HIGH UTILISATION snapshot: feeder=%s util=%.1f%%",
                    feeder_id,
                    utilisation_pct,
                )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("[memory] powerflow snapshot write failed: %s", exc)

    def record_apex_throttle(
        self,
        feeder_id: str,
        throttle_fraction: float,
        reason: str,
        affected_racks: int,
    ) -> None:
        """Record an APEX throttle or load-shed decision.

        Args:
            feeder_id:        Which feeder triggered the throttle
            throttle_fraction: 0.0 = no throttle, 1.0 = full shed
            reason:           Free-text reason (e.g. "N-1 contingency trip")
            affected_racks:   How many racks are derated
        """
        if not self._router:
            return

        payload = {
            "type": "apex_throttle",
            "repo": "xai-colossus-energy",
            "feeder_id": feeder_id,
            "throttle_fraction": throttle_fraction,
            "reason": reason,
            "affected_racks": affected_racks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._router.record_decision(
                source="xai-colossus-energy",
                decision=f"throttle feeder={feeder_id} fraction={throttle_fraction:.2f}",
                context=payload,
            )
            logger.info(
                "[memory] APEX throttle recorded: feeder=%s fraction=%.2f",
                feeder_id,
                throttle_fraction,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("[memory] APEX throttle write failed: %s", exc)

    def recall_recent_incidents(
        self, feeder_id: Optional[str] = None, top_k: int = 5
    ) -> list:
        """Retrieve the most recent energy incidents from memory.

        Args:
            feeder_id: Filter by feeder (None = all feeders)
            top_k:     Number of results to return

        Returns:
            List of memory objects, newest first
        """
        if not self._router:
            return []
        query = f"energy incident alert feeder {feeder_id or ''} high utilisation throttle"
        try:
            return self._router.recall(query=query, top_k=top_k, namespace=self.NAMESPACE)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("[memory] recall failed: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _summarise(result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract key fields to keep vector payloads lean."""
        keys = (
            "passed", "mw_peak", "mw_limit", "headroom_mw",
            "feeder_id", "violations", "water_gph", "duration_s",
        )
        return {k: result[k] for k in keys if k in result}


# Module-level singleton — safe to import multiple times
_bridge: Optional[EnergyMemoryBridge] = None


def get_router() -> EnergyMemoryBridge:
    """Return the module-level EnergyMemoryBridge singleton."""
    global _bridge  # pylint: disable=global-statement
    if _bridge is None:
        _bridge = EnergyMemoryBridge()
    return _bridge
