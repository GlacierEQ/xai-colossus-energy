#!/usr/bin/env python3
"""
Colossus Energy — Grid Balancer
GlacierEQ APEX Stack

Manages 1.5GW power grid balancing for 200k-GPU AI supercomputer.
Implements the Subsystem Interface Contract: tick() + summary().
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Colossus.Energy.GridBalancer")


class GridState(Enum):
    NOMINAL = "NOMINAL"
    STRESSED = "STRESSED"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"
    MAINTENANCE = "MAINTENANCE"


@dataclass
class PowerSource:
    source_id: str
    source_type: str  # "utility", "solar", "battery", "generator"
    capacity_mw: float
    current_output_mw: float = 0.0
    efficiency: float = 0.95
    status: str = "active"

    @property
    def utilization_pct(self) -> float:
        return (self.current_output_mw / self.capacity_mw * 100) if self.capacity_mw > 0 else 0.0

    @property
    def headroom_mw(self) -> float:
        return self.capacity_mw - self.current_output_mw


@dataclass
class GridBalancer:
    """1.5GW grid load balancer with automatic failover."""
    
    total_capacity_mw: float = 1500.0
    critical_threshold_pct: float = 90.0
    warning_threshold_pct: float = 75.0
    
    sources: List[PowerSource] = field(default_factory=list)
    state: GridState = GridState.NOMINAL
    tick_count: int = 0
    anomalies: List[Dict[str, Any]] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if not self.sources:
            self.sources = [
                PowerSource("UTILITY-01", "utility", 800.0, efficiency=0.98),
                PowerSource("SOLAR-01", "solar", 200.0, efficiency=0.22),
                PowerSource("BATTERY-01", "battery", 300.0, efficiency=0.92),
                PowerSource("GENERATOR-01", "generator", 200.0, efficiency=0.35),
            ]

    @property
    def total_output_mw(self) -> float:
        return sum(s.current_output_mw for s in self.sources if s.status == "active")

    @property
    def utilization_pct(self) -> float:
        return (self.total_output_mw / self.total_capacity_mw * 100) if self.total_capacity_mw > 0 else 0.0

    @property
    def total_headroom_mw(self) -> float:
        return sum(s.headroom_mw for s in self.sources if s.status == "active")

    async def tick(self, zones: Dict, tick_num: int) -> Dict[str, Any]:
        """Subsystem Interface Contract: tick() → {anomalies, actions}"""
        self.tick_count = tick_num
        self.anomalies = []
        self.actions = []

        # Simulate load based on GPU utilization
        gpu_load = sum(z.get("gpu_utilization", 0.8) for z in zones.values()) / max(len(zones), 1)
        target_output = self.total_capacity_mw * gpu_load

        # Balance across sources
        await self._balance_load(target_output)

        # Check thresholds
        await self._check_thresholds()

        # Update state
        await self._update_state()

        return {
            "anomalies": self.anomalies,
            "actions": self.actions,
            "state": self.state.value,
            "utilization_pct": self.utilization_pct,
            "total_output_mw": self.total_output_mw,
            "headroom_mw": self.total_headroom_mw,
        }

    async def _balance_load(self, target_mw: float):
        """Distribute load across available sources."""
        remaining = target_mw
        for source in sorted(self.sources, key=lambda s: s.efficiency, reverse=True):
            if source.status != "active":
                continue
            allocation = min(remaining, source.capacity_mw)
            source.current_output_mw = allocation
            remaining -= allocation
            if remaining <= 0:
                break

        if remaining > 0:
            self.anomalies.append({
                "type": "INSUFFICIENT_CAPACITY",
                "severity": "WARN",
                "detail": f"Cannot meet demand: {remaining:.1f} MW shortfall",
            })

    async def _check_thresholds(self):
        """Check utilization thresholds and generate alerts."""
        util = self.utilization_pct
        if util >= self.critical_threshold_pct:
            self.anomalies.append({
                "type": "GRID_CRITICAL",
                "severity": "CRITICAL",
                "detail": f"Utilization {util:.1f}% exceeds {self.critical_threshold_pct}%",
            })
            self.actions.append({
                "action": "ACTIVATE_BACKUP_GENERATORS",
                "target": "GENERATOR-01",
                "reason": "Critical utilization threshold exceeded",
            })
        elif util >= self.warning_threshold_pct:
            self.anomalies.append({
                "type": "GRID_STRESSED",
                "severity": "WARN",
                "detail": f"Utilization {util:.1f}% exceeds {self.warning_threshold_pct}%",
            })

    async def _update_state(self):
        """Update grid state based on anomalies."""
        critical = any(a["severity"] == "CRITICAL" for a in self.anomalies)
        warning = any(a["severity"] == "WARN" for a in self.anomalies)

        if critical:
            self.state = GridState.CRITICAL
        elif warning:
            self.state = GridState.STRESSED
        else:
            self.state = GridState.NOMINAL

    def summary(self) -> Dict[str, Any]:
        """Subsystem Interface Contract: summary() → dict"""
        return {
            "state": self.state.value,
            "total_capacity_mw": self.total_capacity_mw,
            "total_output_mw": self.total_output_mw,
            "utilization_pct": self.utilization_pct,
            "headroom_mw": self.total_headroom_mw,
            "sources": [
                {
                    "id": s.source_id,
                    "type": s.source_type,
                    "capacity_mw": s.capacity_mw,
                    "output_mw": s.current_output_mw,
                    "utilization_pct": s.utilization_pct,
                    "status": s.status,
                }
                for s in self.sources
            ],
            "tick_count": self.tick_count,
        }
