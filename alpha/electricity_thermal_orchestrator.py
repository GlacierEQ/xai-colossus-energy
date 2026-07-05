# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
#!/usr/bin/env python3
"""
ELECTRICITY-THERMAL ORCHESTRATOR
Bidirectional integration between finite power grid and XAI Colossal Cooling.

Manages:
- Power constraints → cooling limits
- Thermal feedback → power allocation
- Real-time constraint propagation
- Predictive throttling to prevent hardware damage

Migrated from GlacierEQ/electricity (now archived).
Canonical home: xai-colossus-energy/electricity/
"""

import json
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum
import heapq


class ConstraintMode(Enum):
    """Grid constraint response modes"""
    NORMAL = "normal"           # Unconstrained operation
    WARNING = "warning"         # >80% utilization, monitor closely
    CONSTRAINED = "constrained" # >95% utilization, throttle non-critical
    CRITICAL = "critical"       # Near max, emergency cooling only


@dataclass
class PowerConstraint:
    """Represents a power constraint event"""
    mode: ConstraintMode
    available_watts: float
    required_watts: float
    margin_percent: float
    throttle_percentage: float
    timestamp: str


@dataclass
class ThermalAlert:
    """Thermal safety alert"""
    gpu_id: str
    current_temp: float
    max_safe_temp: float
    headroom: float
    severity: str  # "info", "warning", "critical"
    recommended_action: str
    timestamp: str


class ElectricityThermalOrchestrator:
    """
    Master orchestrator for electricity-thermal coupling.
    Implements finite-bounded control with predictive throttling.
    """

    def __init__(self, max_power_watts: float, gpu_capacity: int):
        self.max_power_watts = max_power_watts
        self.gpu_capacity = gpu_capacity
        self.allocated_power = 0
        self.constraint_mode = ConstraintMode.NORMAL
        self.gpu_temps: Dict[str, float] = {}
        self.gpu_power_allocations: Dict[str, float] = {}
        self.constraint_history: List[PowerConstraint] = []
        self.thermal_alerts: List[ThermalAlert] = []
        self.trend_queue: List[float] = []
        self.trend_window = 10

    def update_thermal_state(self, gpu_states: Dict[str, float]) -> Dict:
        """Update GPU temps; return constraint decision."""
        self.gpu_temps.update(gpu_states)
        total_power_needed = 0
        thermal_alerts = []

        for gpu_id, temp in gpu_states.items():
            tdp_scale = 1.0 + (temp / 100)
            power = 500 * tdp_scale
            total_power_needed += power
            headroom = max(0, 85 - temp)
            if temp > 80:
                alert = ThermalAlert(
                    gpu_id=gpu_id,
                    current_temp=temp,
                    max_safe_temp=85,
                    headroom=headroom,
                    severity="critical" if temp > 85 else "warning",
                    recommended_action="REDUCE_LOAD" if temp > 80 else "MONITOR",
                    timestamp=datetime.utcnow().isoformat(),
                )
                thermal_alerts.append(alert)
                self.thermal_alerts.append(alert)

        available = self.max_power_watts - total_power_needed
        available_percent = (available / self.max_power_watts) * 100

        if available_percent > 20:
            new_mode, throttle = ConstraintMode.NORMAL, 0
        elif available_percent > 5:
            new_mode, throttle = ConstraintMode.WARNING, 0
        elif available_percent > -5:
            new_mode, throttle = ConstraintMode.CONSTRAINED, 0.15
        else:
            new_mode, throttle = ConstraintMode.CRITICAL, 0.40

        self.constraint_mode = new_mode
        self.allocated_power = total_power_needed

        constraint = PowerConstraint(
            mode=new_mode,
            available_watts=max(0, available),
            required_watts=total_power_needed,
            margin_percent=available_percent,
            throttle_percentage=throttle * 100,
            timestamp=datetime.utcnow().isoformat(),
        )
        self.constraint_history.append(constraint)

        return {
            "constraint_mode": new_mode.value,
            "available_watts": max(0, available),
            "total_power_needed": total_power_needed,
            "utilization_percent": (total_power_needed / self.max_power_watts) * 100,
            "throttle_action": f"Reduce non-critical by {throttle*100:.0f}%" if throttle > 0 else "None",
            "thermal_alerts": [asdict(a) for a in thermal_alerts],
            "avg_gpu_temp_celsius": sum(self.gpu_temps.values()) / len(self.gpu_temps) if self.gpu_temps else 0,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def predictive_constraint_warning(self) -> Optional[Dict]:
        """Linear-extrapolate power trend; warn if constraint <10 min away."""
        if len(self.constraint_history) < 5:
            return None
        utils = [c.margin_percent for c in self.constraint_history[-5:]]
        slope = utils[-1] - utils[0]
        if slope >= 0:
            return None
        points_to_critical = abs(-10 - utils[-1]) / abs(slope)
        minutes_until = points_to_critical * 0.5
        if minutes_until < 10:
            return {
                "minutes_until_constraint": max(0, minutes_until),
                "current_margin_percent": utils[-1],
                "trend_slope": slope,
                "recommended_action": "REDUCE_THERMAL_LOAD_IMMEDIATELY",
                "reason": "Power constraint critical in <10 minutes",
            }
        return None

    def allocate_power_by_priority(self, loads: List[Dict]) -> Dict:
        """Allocate power respecting finite budget; prioritize critical loads."""
        sorted_loads = sorted(loads, key=lambda x: x.get("priority", 0), reverse=True)
        allocated: Dict[str, float] = {}
        total_allocated = 0

        for load in sorted_loads:
            name = load["name"]
            requested = load["watts"]
            is_critical = load.get("is_critical", False)
            available = self.max_power_watts - total_allocated
            if available >= requested:
                allocated[name] = requested
                total_allocated += requested
            elif is_critical and available > 0:
                allocated[name] = available
                total_allocated += available
                break
            else:
                allocated[name] = 0

        return {
            "allocations": allocated,
            "total_allocated_watts": total_allocated,
            "available_watts": self.max_power_watts - total_allocated,
            "utilization_percent": (total_allocated / self.max_power_watts) * 100,
            "constraint_mode": self.constraint_mode.value,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def emergency_shutdown_sequence(self) -> Dict:
        """Initiate emergency power-shed sequence when in CRITICAL mode."""
        if self.constraint_mode != ConstraintMode.CRITICAL:
            return {"initiated": False, "reason": "Not in critical mode"}
        return {
            "initiated": True,
            "actions": [
                "REDUCE memory bandwidth by 50%",
                "DISABLE non-essential sensors",
                "PAUSE batch jobs",
                "ACTIVATE emergency cooling",
                "BEGIN graceful shutdown if power < 10% of max",
            ],
            "estimated_power_savings_watts": self.max_power_watts * 0.4,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def health_report(self) -> Dict:
        """Comprehensive orchestrator health snapshot"""
        return {
            "constraint_mode": self.constraint_mode.value,
            "allocated_power_watts": self.allocated_power,
            "max_power_watts": self.max_power_watts,
            "utilization_percent": (self.allocated_power / self.max_power_watts) * 100,
            "gpu_count_registered": len(self.gpu_temps),
            "avg_gpu_temp_celsius": sum(self.gpu_temps.values()) / len(self.gpu_temps) if self.gpu_temps else 0,
            "max_gpu_temp_celsius": max(self.gpu_temps.values()) if self.gpu_temps else 0,
            "recent_thermal_alerts": len(self.thermal_alerts[-10:]),
            "constraint_events": len(self.constraint_history),
            "predictive_warning": self.predictive_constraint_warning(),
            "timestamp": datetime.utcnow().isoformat(),
        }


class FiniteCoolingBoundary:
    """
    Fundamental constraint: finite cooling capacity → finite power ceiling.
    """

    def __init__(self, cooling_capacity_watts: float, thermal_tlc_celsius: float = 85):
        self.cooling_capacity = cooling_capacity_watts
        self.thermal_tlc = thermal_tlc_celsius

    def max_safe_power(self, current_avg_temp: float) -> float:
        """Given current avg temp, what is max safe power draw?"""
        headroom = self.thermal_tlc - current_avg_temp
        if headroom <= 0:
            return 0
        max_temp_range = self.thermal_tlc - 30
        utilization = max(0, headroom / max_temp_range)
        return self.cooling_capacity * utilization

    def constraint_report(self, current_power: float, current_temp: float) -> Dict:
        max_safe = self.max_safe_power(current_temp)
        margin = max_safe - current_power
        return {
            "cooling_capacity_watts": self.cooling_capacity,
            "current_power_draw_watts": current_power,
            "max_safe_power_watts": max_safe,
            "margin_watts": margin,
            "is_exceeded": current_power > max_safe,
            "current_temp_celsius": current_temp,
            "headroom_celsius": self.thermal_tlc - current_temp,
            "constraint_severity": "CRITICAL" if current_power > max_safe else "WARNING" if margin < 50000 else "NORMAL",
        }
