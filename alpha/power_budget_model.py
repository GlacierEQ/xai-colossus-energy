"""
GW-Scale Power Budget Model with Supabase Persistence
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tracks power budgets at zone and rack level with cascade prevention.
Persists state to Supabase for cross-session durability.
"""

import json
import time
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger("PowerBudgetModel")

try:
    from supabase_utils import write_completion_memory
except ImportError:
    def write_completion_memory(task_id: str, payload: dict) -> None:
        logger.debug(f"Supabase write (stub): {task_id} -> {payload}")


class BudgetViolationType(Enum):
    ZONE_OVER_BUDGET = "zone_over_budget"
    RACK_OVER_BUDGET = "rack_over_budget"
    CASCADE_RISK = "cascade_risk"
    TOTAL_EXCEEDED = "total_exceeded"


@dataclass(frozen=True)
class PowerBudgetConfig:
    facility_total_mw: float = 1500.0
    zone_budgets_mw: Dict[str, float] = field(default_factory=lambda: {
        "A": 500.0,
        "B": 500.0,
        "C": 500.0,
    })
    safety_margin_pct: float = 0.08
    cascade_threshold_pct: float = 0.95
    soft_limit_pct: float = 0.92
    rack_max_kw: float = 11.2

    @property
    def soft_limit_mw(self) -> float:
        return self.facility_total_mw * self.soft_limit_pct

    @property
    def cascade_limit_mw(self) -> float:
        return self.facility_total_mw * self.cascade_threshold_pct

    @property
    def safety_limit_mw(self) -> float:
        return self.facility_total_mw * (1 - self.safety_margin_pct)


@dataclass
class RackBudget:
    rack_id: str
    zone: str
    max_kw: float
    current_kw: float = 0.0
    budget_kw: float = 0.0
    jobs_active: int = 0
    last_updated: float = field(default_factory=time.time)

    @property
    def utilization_pct(self) -> float:
        if self.max_kw <= 0:
            return 0.0
        return (self.current_kw / self.max_kw) * 100

    @property
    def over_budget(self) -> bool:
        return self.budget_kw > 0 and self.current_kw > self.budget_kw

    def to_dict(self) -> Dict:
        return {
            "rack_id": self.rack_id,
            "zone": self.zone,
            "max_kw": round(self.max_kw, 2),
            "current_kw": round(self.current_kw, 2),
            "budget_kw": round(self.budget_kw, 2),
            "utilization_pct": round(self.utilization_pct, 2),
            "over_budget": self.over_budget,
            "jobs_active": self.jobs_active,
        }


@dataclass
class ZoneBudget:
    zone_id: str
    budget_mw: float
    current_mw: float = 0.0
    racks: Dict[str, RackBudget] = field(default_factory=dict)
    shed_targets: List[str] = field(default_factory=list)

    @property
    def headroom_mw(self) -> float:
        return self.budget_mw - self.current_mw

    @property
    def utilization_pct(self) -> float:
        if self.budget_mw <= 0:
            return 0.0
        return (self.current_mw / self.budget_mw) * 100

    @property
    def over_budget(self) -> bool:
        return self.current_mw > self.budget_mw

    def register_rack(self, rack: RackBudget) -> None:
        self.racks[rack.rack_id] = rack
        rack.budget_kw = self.budget_mw * 1000 / max(len(self.racks), 1)

    def compute_total_mw(self) -> float:
        self.current_mw = sum(r.current_kw for r in self.racks.values()) / 1000
        return self.current_mw

    def to_dict(self) -> Dict:
        return {
            "zone_id": self.zone_id,
            "budget_mw": round(self.budget_mw, 2),
            "current_mw": round(self.current_mw, 2),
            "headroom_mw": round(self.headroom_mw, 2),
            "utilization_pct": round(self.utilization_pct, 2),
            "rack_count": len(self.racks),
            "over_budget": self.over_budget,
        }


@dataclass
class BudgetViolation:
    violation_type: BudgetViolationType
    zone_id: str
    rack_id: Optional[str]
    budget_mw: float
    actual_mw: float
    excess_mw: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        return {
            "violation_type": self.violation_type.value,
            "zone_id": self.zone_id,
            "rack_id": self.rack_id,
            "budget_mw": round(self.budget_mw, 2),
            "actual_mw": round(self.actual_mw, 2),
            "excess_mw": round(self.excess_mw, 2),
            "timestamp": self.timestamp,
        }


class SupabaseBudgetStore:
    def __init__(self, persist_path: str = "audit_logs/power_budget_state.jsonl"):
        self.persist_path = Path(persist_path)
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)

    def persist_snapshot(self, snapshot: Dict) -> None:
        entry = {"timestamp": datetime.now().isoformat(), "snapshot": snapshot}
        with open(self.persist_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def load_latest(self) -> Optional[Dict]:
        if not self.persist_path.exists():
            return None
        lines = self.persist_path.read_text().strip().split("\n")
        if not lines:
            return None
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError:
            return None


class PowerBudgetModel:
    def __init__(self, config: Optional[PowerBudgetConfig] = None):
        self.config = config or PowerBudgetConfig()
        self.zones: Dict[str, ZoneBudget] = {}
        self.violations: List[BudgetViolation] = []
        self._violation_callbacks: List = []
        self._store = SupabaseBudgetStore()
        self._init_zones()
        logger.info(
            f"PowerBudgetModel initialized: facility={self.config.facility_total_mw}MW, "
            f"zones={list(self.config.zone_budgets_mw.keys())}"
        )

    def _init_zones(self) -> None:
        for zone_id, budget_mw in self.config.zone_budgets_mw.items():
            self.zones[zone_id] = ZoneBudget(zone_id=zone_id, budget_mw=budget_mw)

    def register_rack(self, rack_id: str, zone_id: str, max_kw: float = 11.2) -> None:
        if zone_id not in self.zones:
            logger.error(f"Zone {zone_id} not found — cannot register rack {rack_id}")
            return
        rack = RackBudget(rack_id=rack_id, zone=zone_id, max_kw=max_kw)
        self.zones[zone_id].register_rack(rack)

    def update_rack_power(self, rack_id: str, zone_id: str, current_kw: float) -> None:
        zone = self.zones.get(zone_id)
        if not zone:
            logger.error(f"Zone {zone_id} not found for rack {rack_id}")
            return
        rack = zone.racks.get(rack_id)
        if not rack:
            logger.warning(f"Rack {rack_id} not registered in zone {zone_id} — auto-registering")
            self.register_rack(rack_id, zone_id)
            rack = zone.racks[rack_id]
        rack.current_kw = current_kw
        rack.last_updated = time.time()

    def compute_totals(self) -> Dict[str, float]:
        totals = {}
        for zone_id, zone in self.zones.items():
            totals[zone_id] = zone.compute_total_mw()
        totals["facility"] = sum(totals.values())
        return totals

    def check_budget_violations(self) -> List[BudgetViolation]:
        new_violations = []
        totals = self.compute_totals()

        for zone_id, zone in self.zones.items():
            if zone.over_budget:
                v = BudgetViolation(
                    violation_type=BudgetViolationType.ZONE_OVER_BUDGET,
                    zone_id=zone_id,
                    rack_id=None,
                    budget_mw=zone.budget_mw,
                    actual_mw=zone.current_mw,
                    excess_mw=zone.current_mw - zone.budget_mw,
                )
                new_violations.append(v)
                logger.warning(f"Zone {zone_id} over budget: {zone.current_mw:.1f}MW > {zone.budget_mw:.1f}MW")

            for rack in zone.racks.values():
                if rack.over_budget:
                    v = BudgetViolation(
                        violation_type=BudgetViolationType.RACK_OVER_BUDGET,
                        zone_id=zone_id,
                        rack_id=rack.rack_id,
                        budget_mw=rack.budget_kw / 1000,
                        actual_mw=rack.current_kw / 1000,
                        excess_mw=(rack.current_kw - rack.budget_kw) / 1000,
                    )
                    new_violations.append(v)

        facility_total = totals.get("facility", 0)
        if facility_total > self.config.cascade_limit_mw:
            v = BudgetViolation(
                violation_type=BudgetViolationType.CASCADE_RISK,
                zone_id="facility",
                rack_id=None,
                budget_mw=self.config.cascade_limit_mw,
                actual_mw=facility_total,
                excess_mw=facility_total - self.config.cascade_limit_mw,
            )
            new_violations.append(v)
            logger.critical(f"CASCADE RISK: facility {facility_total:.1f}MW > {self.config.cascade_limit_mw:.1f}MW")
        elif facility_total > self.config.soft_limit_mw:
            v = BudgetViolation(
                violation_type=BudgetViolationType.TOTAL_EXCEEDED,
                zone_id="facility",
                rack_id=None,
                budget_mw=self.config.soft_limit_mw,
                actual_mw=facility_total,
                excess_mw=facility_total - self.config.soft_limit_mw,
            )
            new_violations.append(v)

        self.violations.extend(new_violations)
        for v in new_violations:
            for cb in self._violation_callbacks:
                try:
                    cb(v)
                except Exception as e:
                    logger.error(f"Violation callback failed: {e}")

        return new_violations

    def compute_shed_plan(self, target_reduction_mw: float) -> Dict[str, float]:
        shed_plan: Dict[str, float] = {}
        remaining = target_reduction_mw
        sorted_zones = sorted(
            self.zones.values(),
            key=lambda z: z.utilization_pct,
            reverse=True,
        )
        for zone in sorted_zones:
            if remaining <= 0:
                break
            available = min(zone.current_mw, remaining)
            if available > 0:
                shed_plan[zone.zone_id] = round(available, 2)
                remaining -= available
        return shed_plan

    def enforce_cascade_prevention(self) -> Tuple[bool, Dict]:
        totals = self.compute_totals()
        facility = totals.get("facility", 0)

        if facility <= self.config.soft_limit_mw:
            return False, {"action": "none", "facility_mw": facility}

        shed_mw = facility - self.config.soft_limit_mw
        shed_plan = self.compute_shed_plan(shed_mw)
        total_shed = sum(shed_plan.values())

        for zone_id, shed_amount in shed_plan.items():
            zone = self.zones.get(zone_id)
            if zone:
                zone.current_mw -= shed_amount
                logger.warning(f"Cascade prevention: shed {shed_amount:.1f}MW from zone {zone_id}")

        return True, {
            "action": "cascade_prevention",
            "shed_plan": shed_plan,
            "total_shed_mw": round(total_shed, 2),
            "facility_before_mw": round(facility, 2),
            "facility_after_mw": round(facility - total_shed, 2),
        }

    def on_violation(self, callback) -> None:
        self._violation_callbacks.append(callback)

    def persist_state(self) -> None:
        snapshot = self.get_full_snapshot()
        self._store.persist_snapshot(snapshot)
        write_completion_memory("POWER_BUDGET_STATE", {
            "facility_mw": snapshot["totals"]["facility"],
            "zones": {z: s["current_mw"] for z, s in snapshot["zones"].items()},
            "violation_count": len(self.violations),
        })

    def get_full_snapshot(self) -> Dict:
        totals = self.compute_totals()
        return {
            "timestamp": datetime.now().isoformat(),
            "config": {
                "facility_total_mw": self.config.facility_total_mw,
                "soft_limit_mw": self.config.soft_limit_mw,
                "cascade_limit_mw": self.config.cascade_limit_mw,
            },
            "zones": {zid: zone.to_dict() for zid, zone in self.zones.items()},
            "totals": totals,
            "violations": [v.to_dict() for v in self.violations[-20:]],
            "rack_count": sum(len(z.racks) for z in self.zones.values()),
        }


if __name__ == "__main__":
    model = PowerBudgetModel()
    model.register_rack("rack-001", "A")
    model.register_rack("rack-002", "A")
    model.register_rack("rack-010", "B")
    model.update_rack_power("rack-001", "A", 8.5)
    model.update_rack_power("rack-002", "A", 9.0)
    model.update_rack_power("rack-010", "B", 7.2)
    totals = model.compute_totals()
    print(f"Totals: {totals}")
    violations = model.check_budget_violations()
    print(f"Violations: {len(violations)}")
    prevented, plan = model.enforce_cascade_prevention()
    print(f"Cascade prevented: {prevented}, plan: {plan}")
    model.persist_state()
    print(f"\nSnapshot: {json.dumps(model.get_full_snapshot(), indent=2)}")
