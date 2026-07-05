# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
"""
APEX Tick Bridge — xai_energy_balancer ↔ APEX Orchestrator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Wires the ColossusEnergyBalancer into the APEX orchestrator tick loop.
Handles telemetry ingestion from MCP, executes control actions, and
emits structured telemetry back to the orchestrator.
"""

import asyncio
import json
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from enum import Enum

logger = logging.getLogger("APEXTickBridge")


class TickPhase(Enum):
    TELEMETRY_INGEST = "telemetry_ingest"
    STATE_COMPUTE = "state_compute"
    CONTROL_ACTION = "control_action"
    TELEMETRY_EMIT = "telemetry_emit"
    COMPLETE = "complete"


class ControlActionType(Enum):
    NONE = "none"
    PEAK_SHAVE = "peak_shave"
    FREQUENCY_RESPONSE = "frequency_response"
    ZONE_SHED = "zone_shed"
    EMERGENCY_SHED = "emergency_shed"
    DEMAND_RESPONSE = "demand_response"


@dataclass
class TelemetryPayload:
    timestamp: float
    source: str
    rack_telemetry: List[Dict] = field(default_factory=list)
    grid_frequency_hz: float = 60.0
    grid_draw_mva: float = 0.0
    megapack_soc_pct: float = 80.0
    solar_output_mw: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict) -> "TelemetryPayload":
        return cls(
            timestamp=data.get("timestamp", time.time()),
            source=data.get("source", "mcp"),
            rack_telemetry=data.get("rack_telemetry", []),
            grid_frequency_hz=data.get("grid_frequency_hz", 60.0),
            grid_draw_mva=data.get("grid_draw_mva", 0.0),
            megapack_soc_pct=data.get("megapack_soc_pct", 80.0),
            solar_output_mw=data.get("solar_output_mw", 0.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TickResult:
    tick_id: int
    phase: TickPhase
    action_taken: ControlActionType
    action_detail: str
    total_draw_mw: float
    headroom_mw: float
    balancer_mode: str
    duration_ms: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "tick_id": self.tick_id,
            "phase": self.phase.value,
            "action_taken": self.action_taken.value,
            "action_detail": self.action_detail,
            "total_draw_mw": round(self.total_draw_mw, 2),
            "headroom_mw": round(self.headroom_mw, 2),
            "balancer_mode": self.balancer_mode,
            "duration_ms": round(self.duration_ms, 2),
            "timestamp": self.timestamp,
            "errors": self.errors,
        }


class APEXTickBridge:
    def __init__(
        self,
        balancer: Any,
        tick_interval_s: float = 0.1,
        telemetry_buffer_size: int = 100,
    ):
        self.balancer = balancer
        self.tick_interval_s = tick_interval_s
        self._tick_count = 0
        self._running = False
        self._telemetry_buffer: List[TelemetryPayload] = []
        self._telemetry_buffer_max = telemetry_buffer_size
        self._tick_history: List[TickResult] = []
        self._tick_history_max = 1000
        self._phase_handlers: Dict[TickPhase, Callable] = {
            TickPhase.TELEMETRY_INGEST: self._phase_telemetry_ingest,
            TickPhase.STATE_COMPUTE: self._phase_state_compute,
            TickPhase.CONTROL_ACTION: self._phase_control_action,
            TickPhase.TELEMETRY_EMIT: self._phase_telemetry_emit,
        }
        self._last_telemetry: Optional[TelemetryPayload] = None
        self._control_action_type = ControlActionType.NONE
        self._control_action_detail = ""
        self._emitted_events: List[Dict] = []
        logger.info(f"APEXTickBridge initialized: tick_interval={tick_interval_s}s")

    def ingest_telemetry(self, payload: TelemetryPayload) -> None:
        if len(self._telemetry_buffer) >= self._telemetry_buffer_max:
            self._telemetry_buffer.pop(0)
        self._telemetry_buffer.append(payload)
        self._last_telemetry = payload

    def _phase_telemetry_ingest(self, tick_id: int) -> None:
        if not self._telemetry_buffer:
            return
        payload = self._telemetry_buffer[-1]
        if hasattr(self.balancer, "ingest_telemetry") and payload.rack_telemetry:
            self.balancer.ingest_telemetry(payload.rack_telemetry)
        if hasattr(self.balancer, "grid_state"):
            self.balancer.grid_state.grid_frequency_hz = payload.grid_frequency_hz
            self.balancer.grid_state.grid_draw_mva = payload.grid_draw_mva
            self.balancer.grid_state.megapack_soc_pct = payload.megapack_soc_pct
            self.balancer.grid_state.solar_output_mw = payload.solar_output_mw

    def _phase_state_compute(self, tick_id: int) -> None:
        if not hasattr(self.balancer, "compute_total_draw_mw"):
            return
        total_mw = self.balancer.compute_total_draw_mw()
        if hasattr(self.balancer, "grid_state"):
            self.balancer.grid_state.grid_draw_mva = total_mw
        self._control_action_type = ControlActionType.NONE
        self._control_action_detail = "nominal"
        soft_limit = getattr(self.balancer, "soft_limit_mw", 150.0)
        cascade_limit = getattr(self.balancer, "cascade_limit_mw", 142.5)
        if total_mw > cascade_limit:
            self._control_action_type = ControlActionType.EMERGENCY_SHED
            self._control_action_detail = f"cascade_risk: {total_mw:.1f}MW > {cascade_limit:.1f}MW"
        elif total_mw > soft_limit:
            self._control_action_type = ControlActionType.PEAK_SHAVE
            self._control_action_detail = f"peak_shave: {total_mw:.1f}MW > {soft_limit:.1f}MW"

    def _phase_control_action(self, tick_id: int) -> None:
        if self._control_action_type == ControlActionType.NONE:
            return
        if self._control_action_type == ControlActionType.EMERGENCY_SHED:
            if hasattr(self.balancer, "_execute_control_action"):
                from xai_energy_balancer import GridMode
                self.balancer._execute_control_action(
                    GridMode.EMERGENCY_SHED,
                    self.balancer.compute_total_draw_mw(),
                )
        elif self._control_action_type == ControlActionType.PEAK_SHAVE:
            if hasattr(self.balancer, "megapack") and hasattr(self.balancer.megapack, "peak_shave"):
                excess = self.balancer.compute_total_draw_mw() - self.balancer.soft_limit_mw
                self.balancer.megapack.peak_shave(excess)

    def _phase_telemetry_emit(self, tick_id: int) -> None:
        total_mw = 0.0
        if hasattr(self.balancer, "compute_total_draw_mw"):
            total_mw = self.balancer.compute_total_draw_mw()
        headroom = 0.0
        if hasattr(self.balancer, "grid_state"):
            headroom = self.balancer.grid_state.headroom_mw
        balancer_mode = "unknown"
        if hasattr(self.balancer, "grid_state") and hasattr(self.balancer.grid_state, "grid_mode"):
            balancer_mode = self.balancer.grid_state.grid_mode.value
        event = {
            "type": "tick_telemetry",
            "tick_id": tick_id,
            "total_draw_mw": total_mw,
            "headroom_mw": headroom,
            "action": self._control_action_type.value,
            "balancer_mode": balancer_mode,
            "timestamp": datetime.now().isoformat(),
        }
        self._emitted_events.append(event)
        if hasattr(self.balancer, "dispatch_mcp_event"):
            self.balancer.dispatch_mcp_event("tick_telemetry", event)

    async def execute_tick(self) -> TickResult:
        start_time = time.time()
        self._tick_count += 1
        errors: List[str] = []
        phase = TickPhase.COMPLETE

        for tick_phase in [
            TickPhase.TELEMETRY_INGEST,
            TickPhase.STATE_COMPUTE,
            TickPhase.CONTROL_ACTION,
            TickPhase.TELEMETRY_EMIT,
        ]:
            try:
                self._phase_handlers[tick_phase](self._tick_count)
                phase = tick_phase
            except Exception as e:
                errors.append(f"{tick_phase.value}: {str(e)}")
                logger.error(f"Tick {self._tick_count} phase {tick_phase.value} failed: {e}")
                break

        duration_ms = (time.time() - start_time) * 1000
        total_mw = 0.0
        headroom = 0.0
        balancer_mode = "unknown"
        if hasattr(self.balancer, "compute_total_draw_mw"):
            total_mw = self.balancer.compute_total_draw_mw()
        if hasattr(self.balancer, "grid_state"):
            headroom = self.balancer.grid_state.headroom_mw
            if hasattr(self.balancer.grid_state, "grid_mode"):
                balancer_mode = self.balancer.grid_state.grid_mode.value

        result = TickResult(
            tick_id=self._tick_count,
            phase=phase,
            action_taken=self._control_action_type,
            action_detail=self._control_action_detail,
            total_draw_mw=total_mw,
            headroom_mw=headroom,
            balancer_mode=balancer_mode,
            duration_ms=duration_ms,
            errors=errors,
        )

        if len(self._tick_history) >= self._tick_history_max:
            self._tick_history.pop(0)
        self._tick_history.append(result)
        return result

    async def run_loop(self, max_ticks: Optional[int] = None) -> None:
        self._running = True
        logger.info(f"APEXTickBridge loop started: interval={self.tick_interval_s}s")
        tick_count = 0
        while self._running:
            result = await self.execute_tick()
            tick_count += 1
            if max_ticks and tick_count >= max_ticks:
                break
            await asyncio.sleep(self.tick_interval_s)
        self._running = False
        logger.info(f"APEXTickBridge loop stopped after {tick_count} ticks")

    def stop(self) -> None:
        self._running = False

    def get_tick_history(self, limit: int = 10) -> List[Dict]:
        return [t.to_dict() for t in self._tick_history[-limit:]]

    def get_emitted_events(self, limit: int = 10) -> List[Dict]:
        return self._emitted_events[-limit:]

    def get_status(self) -> Dict:
        return {
            "running": self._running,
            "total_ticks": self._tick_count,
            "tick_interval_s": self.tick_interval_s,
            "telemetry_buffer_size": len(self._telemetry_buffer),
            "tick_history_size": len(self._tick_history),
            "last_telemetry_age_s": (
                time.time() - self._last_telemetry.timestamp
                if self._last_telemetry
                else None
            ),
            "last_action": self._control_action_type.value,
        }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/data/data/com.termux/files/home/xai-colossus-energy")
    from xai_energy_balancer import ColossusEnergyBalancer

    balancer = ColossusEnergyBalancer()
    bridge = APEXTickBridge(balancer=balancer, tick_interval_s=0.05)

    async def demo():
        payload = TelemetryPayload(
            timestamp=time.time(),
            source="demo",
            grid_frequency_hz=59.95,
            grid_draw_mva=120.0,
            megapack_soc_pct=75.0,
        )
        bridge.ingest_telemetry(payload)
        await bridge.run_loop(max_ticks=20)
        print(f"Status: {bridge.get_status()}")
        print(f"Last 3 ticks: {bridge.get_tick_history(3)}")

    asyncio.run(demo())
