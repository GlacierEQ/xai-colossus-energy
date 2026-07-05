# Omega (How) — Controllers | Alpha (What) — Pure Physics | 1337.
"""EnergyMemoryBridge — wraps colossus-gateway MemoryRouter for energy-specific writes.

Every gauntlet run, powerflow scenario, and APEX throttle decision is dual-written
to Pinecone (semantic vector) and Supermemory (conversational context).
"""
from __future__ import annotations

import os
import time
import json
from dataclasses import dataclass, asdict
from typing import Any

# ── Optional import — graceful degradation if gateway not installed ──────────
try:
    import sys
    sys.path.insert(0, os.environ.get("COLOSSUS_GATEWAY_PATH", "../colossus-gateway"))
    from src.memory.memory_router import MemoryRouter
    _ROUTER_AVAILABLE = True
except ImportError:
    _ROUTER_AVAILABLE = False
    MemoryRouter = None  # type: ignore


@dataclass
class EnergyScenario:
    """Structured energy scenario result written to both memory backends."""
    scenario_id: str
    scenario_type: str          # powerflow | gauntlet | throttle | ej_alert
    timestamp: float
    total_mw: float
    feeder_headroom_mw: float
    grid_limit_mw: float
    safe: bool
    throttle_fraction: float    # 0.0 = no throttle, 1.0 = full shed
    emissions_proxy_kg_co2: float
    water_use_gallons: float
    affected_zip_codes: list[str]
    notes: str = ""
    raw: dict | None = None


class EnergyMemoryBridge:
    """Writes energy events to Pinecone + Supermemory via colossus-gateway MemoryRouter.

    Falls back silently if the gateway is not reachable — energy logic is never blocked
    by a memory backend outage.
    """

    NAMESPACE = "colossus-scenarios"
    SPACE_KEY = "scenarios"

    def __init__(self) -> None:
        self._router: Any = None
        if _ROUTER_AVAILABLE:
            try:
                self._router = MemoryRouter()
            except Exception as exc:
                print(f"[EnergyMemoryBridge] Router init failed (degraded): {exc}")

    # ── Public API ────────────────────────────────────────────────────────────

    def remember_scenario(self, scenario: EnergyScenario) -> bool:
        """Dual-write a scenario result to Pinecone + Supermemory.

        Returns True if at least one backend accepted the write.
        """
        if self._router is None:
            return self._fallback_log(scenario)

        content = self._scenario_to_text(scenario)
        metadata = {
            "scenario_type": scenario.scenario_type,
            "safe": scenario.safe,
            "total_mw": scenario.total_mw,
            "throttle_fraction": scenario.throttle_fraction,
            "emissions_proxy_kg_co2": scenario.emissions_proxy_kg_co2,
            "water_use_gallons": scenario.water_use_gallons,
            "affected_zip_codes": ",".join(scenario.affected_zip_codes),
            "timestamp": scenario.timestamp,
            "repo": "xai-colossus-energy",
        }

        try:
            return self._router.remember_scenario(
                scenario_id=scenario.scenario_id,
                content=content,
                metadata=metadata,
                namespace=self.NAMESPACE,
                space_key=self.SPACE_KEY,
            )
        except Exception as exc:
            print(f"[EnergyMemoryBridge] remember_scenario failed: {exc}")
            return self._fallback_log(scenario)

    def record_throttle_decision(
        self,
        scenario_id: str,
        reason: str,
        throttle_fraction: float,
        triggered_by: str = "gauntlet",
    ) -> bool:
        """Record an APEX throttle or load-shed decision for audit continuity."""
        if self._router is None:
            print(f"[EnergyMemoryBridge][fallback] throttle decision: {scenario_id} → {throttle_fraction:.0%}")
            return False

        try:
            return self._router.record_decision(
                decision_id=f"throttle-{scenario_id}-{int(time.time())}",
                content=(
                    f"APEX throttle decision: {throttle_fraction:.0%} load shed. "
                    f"Triggered by: {triggered_by}. Reason: {reason}"
                ),
                metadata={
                    "scenario_id": scenario_id,
                    "throttle_fraction": throttle_fraction,
                    "triggered_by": triggered_by,
                    "repo": "xai-colossus-energy",
                },
            )
        except Exception as exc:
            print(f"[EnergyMemoryBridge] record_throttle_decision failed: {exc}")
            return False

    def recall_similar(
        self,
        query: str,
        top_k: int = 5,
        filter_safe_only: bool = False,
    ) -> list[dict]:
        """Semantic recall of similar past energy scenarios from Pinecone."""
        if self._router is None:
            return []

        kwargs: dict = {"namespace": self.NAMESPACE}
        if filter_safe_only:
            kwargs["filter"] = {"safe": True}

        try:
            return self._router.recall(
                query=query,
                top_k=top_k,
                **kwargs,
            )
        except Exception as exc:
            print(f"[EnergyMemoryBridge] recall_similar failed: {exc}")
            return []

    def health(self) -> dict:
        """Return health status of both memory backends."""
        if self._router is None:
            return {"pinecone": "unavailable", "supermemory": "unavailable", "gateway": "not_installed"}
        try:
            return self._router.health()
        except Exception as exc:
            return {"error": str(exc)}

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _scenario_to_text(s: EnergyScenario) -> str:
        safe_str = "SAFE" if s.safe else "UNSAFE"
        zips = ", ".join(s.affected_zip_codes) if s.affected_zip_codes else "none"
        return (
            f"[{s.scenario_type.upper()}] Scenario {s.scenario_id} — {safe_str}. "
            f"Total draw: {s.total_mw:.1f} MW (limit {s.grid_limit_mw:.1f} MW, "
            f"headroom {s.feeder_headroom_mw:.1f} MW). "
            f"Throttle: {s.throttle_fraction:.0%}. "
            f"Emissions proxy: {s.emissions_proxy_kg_co2:.1f} kg CO2/h. "
            f"Water use: {s.water_use_gallons:.0f} gal/h. "
            f"Affected ZIP codes: {zips}. "
            f"Notes: {s.notes}"
        )

    @staticmethod
    def _fallback_log(scenario: EnergyScenario) -> bool:
        """Write to stdout when memory router is unavailable."""
        print(f"[EnergyMemoryBridge][fallback] {json.dumps(asdict(scenario), default=str)}")
        return False
