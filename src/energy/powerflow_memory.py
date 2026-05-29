"""Powerflow memory integration — writes each powerflow run result to the memory layer.

Import this module anywhere in xai_energy_balancer.py or gauntlet_integration/ that
produces a final scenario result, then call `emit_powerflow_result()`.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from src.memory.memory_bridge import EnergyMemoryBridge, EnergyScenario

_bridge = EnergyMemoryBridge()


def emit_powerflow_result(
    total_mw: float,
    feeder_headroom_mw: float,
    grid_limit_mw: float,
    safe: bool,
    throttle_fraction: float,
    emissions_proxy_kg_co2: float,
    water_use_gallons: float,
    affected_zip_codes: list[str] | None = None,
    scenario_type: str = "powerflow",
    notes: str = "",
    raw: dict | None = None,
) -> str:
    """Emit a powerflow run to memory. Returns the scenario_id written."""
    scenario_id = f"{scenario_type}-{uuid.uuid4().hex[:8]}"
    scenario = EnergyScenario(
        scenario_id=scenario_id,
        scenario_type=scenario_type,
        timestamp=time.time(),
        total_mw=total_mw,
        feeder_headroom_mw=feeder_headroom_mw,
        grid_limit_mw=grid_limit_mw,
        safe=safe,
        throttle_fraction=throttle_fraction,
        emissions_proxy_kg_co2=emissions_proxy_kg_co2,
        water_use_gallons=water_use_gallons,
        affected_zip_codes=affected_zip_codes or [],
        notes=notes,
        raw=raw,
    )
    _bridge.remember_scenario(scenario)

    if not safe and throttle_fraction > 0:
        _bridge.record_throttle_decision(
            scenario_id=scenario_id,
            reason=notes or "powerflow limit exceeded",
            throttle_fraction=throttle_fraction,
            triggered_by=scenario_type,
        )

    return scenario_id


def recall_similar_scenarios(query: str, top_k: int = 5, safe_only: bool = False) -> list[dict]:
    """Retrieve semantically similar past scenarios from Pinecone."""
    return _bridge.recall_similar(query, top_k=top_k, filter_safe_only=safe_only)


def memory_health() -> dict:
    """Check memory backend health."""
    return _bridge.health()
