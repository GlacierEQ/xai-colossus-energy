#!/usr/bin/env python3
"""
ELECTRICITY APEX BOOT CORE
Finite-Bounded Power Grid Physics Engine
Integrates with XAI Colossal Cooling via thermal-power correlation

First-principles power distribution for GPU thermal management.
Budget: 100-500kW depending on scale (8→8000 GPUs)

Migrated from GlacierEQ/electricity (now archived).
Canonical home: xai-colossus-energy/electricity/
"""

import json
import math
import time
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

# ============================================================================
# APEX CORE: FINITE POWER BUDGETS (First-Principles Physics)
# ============================================================================

class GridTier(Enum):
    """Power delivery tiers (finite bounded stages)"""
    MICRO = (8, 10)        # 8 GPUs, 10kW max
    MINI = (32, 40)        # 32 GPUs, 40kW max
    STANDARD = (128, 150)  # 128 GPUs, 150kW max
    COLOSSAL = (512, 600)  # 512 GPUs, 600kW max
    MEGA = (8000, 5000)    # 8000 GPUs, 5000kW max


@dataclass
class PowerBudget:
    """Immutable power allocation for a tier"""
    tier: GridTier
    gpu_count: int
    max_watts: float
    allocated_watts: float
    reserved_watts: float  # Headroom for thermal spikes

    def available_watts(self) -> float:
        """Remaining unallocated power in budget"""
        return self.max_watts - self.allocated_watts - self.reserved_watts

    def utilization_percent(self) -> float:
        """Current budget utilization (0-100%)"""
        return (self.allocated_watts / self.max_watts) * 100

    def is_constrained(self) -> bool:
        """True if available power < 10% buffer"""
        return self.available_watts() < (self.max_watts * 0.1)


@dataclass
class ThermalPowerCorrelation:
    """Physics: relates GPU temp → power draw (first-principles)"""
    base_tdp: float            # Watts per GPU at idle
    temp_coefficient: float    # W/°C change in power draw
    cooling_efficiency: float  # % of power converted to heat removal (0-1)

    def power_from_temp(self, temp_celsius: float, tdp_scale: float = 1.0) -> float:
        """
        Calculate power draw from GPU temp.
        Higher temp → higher power (thermal runaway risk).
        """
        base = self.base_tdp * tdp_scale
        temp_offset = max(0, temp_celsius - 30)  # Reference: 30°C idle
        power = base + (temp_offset * self.temp_coefficient)
        return max(base, power)  # Never below base TDP

    def thermal_headroom(self, current_temp: float, max_safe_temp: float = 85) -> float:
        """Margin before thermal throttle (in °C)"""
        return max(0, max_safe_temp - current_temp)


class APEXPowerGrid:
    """
    APEX-level power grid orchestrator.
    Manages finite power budgets with thermal-aware allocation.
    """

    def __init__(self, tier: GridTier):
        self.tier = tier
        self.gpu_count, max_watts = tier.value

        # Budget: 80% usable, 20% reserved for thermal spikes
        self.budget = PowerBudget(
            tier=tier,
            gpu_count=self.gpu_count,
            max_watts=max_watts,
            allocated_watts=0,
            reserved_watts=max_watts * 0.2,
        )

        # Thermal correlation (calibrated for NVIDIA H100/B100/Blackwell)
        self.thermal = ThermalPowerCorrelation(
            base_tdp=500,          # W per GPU at idle
            temp_coefficient=5.0,  # W/°C
            cooling_efficiency=0.85,
        )

        # GPU registry: {gpu_id: (temp, power_draw, thermal_headroom)}
        self.gpu_states: Dict[str, Dict] = {}

        # Power allocation history (for trending)
        self.allocation_history: List[Tuple[datetime, float]] = []

    def register_gpu(self, gpu_id: str) -> None:
        """Register a GPU in the power grid"""
        self.gpu_states[gpu_id] = {
            "temp_celsius": 30,
            "power_watts": self.thermal.base_tdp,
            "throttled": False,
            "last_update": datetime.utcnow(),
        }

    def update_gpu_temp(self, gpu_id: str, temp_celsius: float) -> Dict:
        """Update GPU temperature; recalculate power draw."""
        if gpu_id not in self.gpu_states:
            self.register_gpu(gpu_id)

        gpu = self.gpu_states[gpu_id]
        tdp_scale = 1.0 + (temp_celsius / 100)
        power = self.thermal.power_from_temp(temp_celsius, tdp_scale)
        headroom = self.thermal.thermal_headroom(temp_celsius)
        throttled = temp_celsius > 85

        gpu.update({
            "temp_celsius": temp_celsius,
            "power_watts": power,
            "throttled": throttled,
            "headroom": headroom,
            "last_update": datetime.utcnow(),
        })
        return gpu

    def allocate_power(self, allocations: Dict[str, float]) -> Dict:
        """Allocate power to GPUs. Respects finite budget."""
        total_requested = sum(allocations.values())
        available = self.budget.available_watts()
        warnings = []

        if total_requested > available:
            scale = available / total_requested
            allocations = {k: v * scale for k, v in allocations.items()}
            warnings.append(f"CONSTRAINT: scaled allocations to {scale:.2%}")

        self.budget.allocated_watts = sum(allocations.values())
        self.allocation_history.append((datetime.utcnow(), self.budget.allocated_watts))

        return {
            "success": len(warnings) == 0,
            "allocated_watts": self.budget.allocated_watts,
            "available_watts": self.budget.available_watts(),
            "utilization_percent": self.budget.utilization_percent(),
            "is_constrained": self.budget.is_constrained(),
            "warnings": warnings,
        }

    def grid_status(self) -> Dict:
        """Real-time grid health snapshot"""
        temps = [g["temp_celsius"] for g in self.gpu_states.values()]
        powers = [g["power_watts"] for g in self.gpu_states.values()]
        headrooms = [g.get("headroom", 0) for g in self.gpu_states.values()]
        throttled_count = sum(1 for g in self.gpu_states.values() if g.get("throttled", False))

        return {
            "tier": self.tier.name,
            "gpu_count": self.gpu_count,
            "registered_gpus": len(self.gpu_states),
            "avg_temp_celsius": sum(temps) / len(temps) if temps else 0,
            "max_temp_celsius": max(temps) if temps else 0,
            "total_power_watts": sum(powers),
            "budget_watts": self.budget.max_watts,
            "allocated_percent": self.budget.utilization_percent(),
            "available_watts": self.budget.available_watts(),
            "min_headroom_celsius": min(headrooms) if headrooms else 0,
            "gpus_throttled": throttled_count,
            "is_constrained": self.budget.is_constrained(),
            "timestamp": datetime.utcnow().isoformat(),
        }


class ThermalPowerFeedback:
    """
    Links XAI Colossal Cooling → Electricity grid.
    Bidirectional: cooling demand → power allocation → thermal feedback.
    """

    def __init__(self, grid: APEXPowerGrid):
        self.grid = grid
        self.feedback_log: List[Dict] = []

    def cooling_to_power(self, cooling_demand_watts: float) -> Dict:
        """Translate cooling demand into power allocation request."""
        required_power = cooling_demand_watts / self.grid.thermal.cooling_efficiency
        available = self.grid.budget.available_watts()
        can_fulfill = required_power <= available
        allocated = min(required_power, available)

        feedback = {
            "cooling_demand_watts": cooling_demand_watts,
            "required_power_watts": required_power,
            "allocated_power_watts": allocated,
            "can_fulfill": can_fulfill,
            "constrained": required_power > available,
            "constraint_margin_watts": available - required_power,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.feedback_log.append(feedback)
        return feedback

    def power_to_thermal_impact(self, power_watts: float) -> float:
        """Given power allocation, estimate thermal impact (80% → heat)."""
        return power_watts * 0.8
