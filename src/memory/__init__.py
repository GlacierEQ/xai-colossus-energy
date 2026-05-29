"""Energy memory bridge — re-exports colossus-gateway MemoryRouter.

Usage:
    from src.memory import get_router
    router = get_router()
    router.remember_scenario("energy", {...})
"""
from .energy_memory_bridge import EnergyMemoryBridge, get_router

__all__ = ["EnergyMemoryBridge", "get_router"]
