# Omega (How) — Controllers | Alpha (What) — Pure Physics | 1337.
"""
ELECTRICITY ⇔ XAI COLOSSAL COOLING REAL-TIME BRIDGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FastAPI service for bidirectional real-time power control.
- Electricity grid broadcasts constraint events
- XAI cooling system responds with thermal updates
- Closed-loop throttling & priority allocation

Migrated from GlacierEQ/electricity (now archived).
Canonical home: xai-colossus-energy/electricity/
"""

from fastapi import FastAPI, HTTPException, WebSocket, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, List, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import asyncio
import json
import logging
from datetime import datetime
import uvicorn


class ConstraintMode(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CONSTRAINED = "CONSTRAINED"
    CRITICAL = "CRITICAL"


class ThermalUpdate(BaseModel):
    timestamp: str
    gpu_count: int
    avg_temp_c: float
    max_temp_c: float
    cooling_load_watts: int
    coolant_temp_c: float
    pump_rpm: int
    thermal_headroom_c: float


class PowerConstraint(BaseModel):
    timestamp: str
    constraint_mode: ConstraintMode
    available_power_watts: int
    max_gpu_power_watts: int
    throttle_percentage: float
    time_to_critical_minutes: Optional[float]
    forecast_watts: Optional[int]
    recommendation: str


class ThrottleCommand(BaseModel):
    gpu_ids: List[int]
    throttle_percent: float
    duration_seconds: Optional[int]
    reason: str


class BridgeStatus(BaseModel):
    status: str
    electricity_connected: bool
    xai_colossal_connected: bool
    last_thermal_update: Optional[str]
    last_power_constraint: Optional[str]
    active_throttles: int
    queued_events: int


class ElectricityXAIBridge:
    """Bidirectional FastAPI bridge between electricity & xai-colossal-cooling."""

    def __init__(self):
        self.app = FastAPI(
            title="Electricity ⇔ XAI Colossal Cooling Bridge",
            version="1.0.0",
            description="Real-time power constraint & thermal feedback loop",
        )
        self.electricity_connected = False
        self.xai_colossal_connected = False
        self.last_thermal_update: Optional[ThermalUpdate] = None
        self.last_power_constraint: Optional[PowerConstraint] = None
        self.active_throttles: Dict[int, ThrottleCommand] = {}
        self.event_queue: List[Dict] = []
        self.subscribers: List[Callable] = []
        self._setup_routes()

    def _setup_routes(self):
        @self.app.post("/thermal/update")
        async def receive_thermal_update(update: ThermalUpdate):
            self.xai_colossal_connected = True
            self.last_thermal_update = update
            event = {"type": "thermal_update", "timestamp": update.timestamp, "payload": update.dict()}
            self.event_queue.append(event)
            for sub in self.subscribers:
                try:
                    sub(event)
                except Exception as e:
                    logging.warning(f"Subscriber error: {e}")
            return {"status": "received", "event_id": len(self.event_queue), "next_poll_seconds": 2}

        @self.app.post("/power/constraint")
        async def receive_power_constraint(constraint: PowerConstraint):
            self.electricity_connected = True
            self.last_power_constraint = constraint
            event = {"type": "power_constraint", "timestamp": constraint.timestamp, "payload": constraint.dict()}
            self.event_queue.append(event)
            if constraint.constraint_mode == ConstraintMode.CRITICAL:
                throttle = self._emergency_throttle(constraint)
                return {"status": "constraint_received", "mode": constraint.constraint_mode, "emergency_action": throttle.dict()}
            return {"status": "constraint_received", "mode": constraint.constraint_mode}

        @self.app.post("/throttle/apply")
        async def apply_throttle(cmd: ThrottleCommand):
            for gpu_id in cmd.gpu_ids:
                self.active_throttles[gpu_id] = cmd
            self.event_queue.append({"type": "throttle_command", "timestamp": datetime.utcnow().isoformat(), "payload": cmd.dict()})
            return {"status": "throttle_applied", "gpu_count": len(cmd.gpu_ids), "throttle_percent": cmd.throttle_percent}

        @self.app.get("/status", response_model=BridgeStatus)
        async def get_bridge_status():
            return BridgeStatus(
                status="healthy" if (self.electricity_connected and self.xai_colossal_connected) else "degraded",
                electricity_connected=self.electricity_connected,
                xai_colossal_connected=self.xai_colossal_connected,
                last_thermal_update=self.last_thermal_update.timestamp if self.last_thermal_update else None,
                last_power_constraint=self.last_power_constraint.timestamp if self.last_power_constraint else None,
                active_throttles=len(self.active_throttles),
                queued_events=len(self.event_queue),
            )

        @self.app.get("/events/recent")
        async def get_recent_events(limit: int = 20):
            return self.event_queue[-limit:]

        @self.app.get("/thermal/latest")
        async def get_latest_thermal():
            return self.last_thermal_update

        @self.app.get("/power/constraint/latest")
        async def get_latest_constraint():
            return self.last_power_constraint

        @self.app.post("/system/reset")
        async def reset_bridge():
            self.active_throttles.clear()
            self.event_queue.clear()
            return {"status": "reset_complete", "throttles_cleared": True}

        @self.app.websocket("/ws/events")
        async def websocket_events(websocket: WebSocket):
            await websocket.accept()
            try:
                while True:
                    if self.event_queue:
                        await websocket.send_json(self.event_queue[-1])
                    await asyncio.sleep(1)
            except Exception as e:
                logging.warning(f"WebSocket closed: {e}")

    def _emergency_throttle(self, constraint: PowerConstraint) -> ThrottleCommand:
        return ThrottleCommand(
            gpu_ids=list(range(0, 8)),
            throttle_percent=50.0,
            duration_seconds=300,
            reason=f"Emergency: {constraint.recommendation}",
        )

    def register_subscriber(self, callback: Callable):
        self.subscribers.append(callback)

    def get_app(self):
        return self.app


class PowerAllocationEngine:
    """Intelligent power allocation based on workload priority."""

    def __init__(self, bridge: ElectricityXAIBridge):
        self.bridge = bridge
        self.workloads: Dict[int, Dict] = {}

    def register_workload(self, gpu_id: int, priority: str, workload_type: str):
        self.workloads[gpu_id] = {"priority": priority, "workload_type": workload_type}

    def calculate_throttle_targets(self, constraint: PowerConstraint) -> List[int]:
        if constraint.constraint_mode == ConstraintMode.NORMAL:
            return []
        targets = []
        for gpu_id, w in self.workloads.items():
            p = w["priority"]
            if constraint.constraint_mode == ConstraintMode.WARNING and p == "LOW":
                targets.append(gpu_id)
            elif constraint.constraint_mode == ConstraintMode.CONSTRAINED and p in ("LOW", "NORMAL"):
                targets.append(gpu_id)
            elif constraint.constraint_mode == ConstraintMode.CRITICAL and p != "CRITICAL":
                targets.append(gpu_id)
        return targets


if __name__ == "__main__":
    bridge = ElectricityXAIBridge()
    engine = PowerAllocationEngine(bridge)
    print("""
    ╔═════════════════════════════════════════════════════════════╗
    ║  ELECTRICITY ⇔ XAI COLOSSAL COOLING BRIDGE                ║
    ║  API:  http://localhost:8000                               ║
    ║  Docs: http://localhost:8000/docs                          ║
    ║  WS:   ws://localhost:8000/ws/events                       ║
    ╚═════════════════════════════════════════════════════════════╝
    """)
    uvicorn.run(bridge.get_app(), host="0.0.0.0", port=8000, log_level="info")
