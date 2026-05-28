"""
electricity — Finite-Bounded Power Grid Physics Engine
=======================================================
Migrated from standalone `electricity` repo (GlacierEQ/electricity).
Canonical home: xai-colossus-energy/electricity/

Public surface:
    APEXPowerGrid, GridTier, PowerBudget, ThermalPowerCorrelation
    ElectricityThermalOrchestrator, FiniteCoolingBoundary, ConstraintMode
    ElectricityXAIBridge, PowerAllocationEngine
    ElectricityCLI

Do NOT import from the legacy `electricity` repo — it is archived.
"""

from .electricity_apex_boot_core import (
    APEXPowerGrid,
    GridTier,
    PowerBudget,
    ThermalPowerCorrelation,
    ThermalPowerFeedback,
)
from .electricity_thermal_orchestrator import (
    ElectricityThermalOrchestrator,
    FiniteCoolingBoundary,
    ConstraintMode,
    PowerConstraint,
    ThermalAlert,
)
from .electricity_xai_bridge import (
    ElectricityXAIBridge,
    PowerAllocationEngine,
)

__all__ = [
    # Boot core / grid
    "APEXPowerGrid",
    "GridTier",
    "PowerBudget",
    "ThermalPowerCorrelation",
    "ThermalPowerFeedback",
    # Orchestrator
    "ElectricityThermalOrchestrator",
    "FiniteCoolingBoundary",
    "ConstraintMode",
    "PowerConstraint",
    "ThermalAlert",
    # Bridge
    "ElectricityXAIBridge",
    "PowerAllocationEngine",
]
