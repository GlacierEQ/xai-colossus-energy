# Omega (How) — Controllers | Alpha (What) — Pure Physics | 1337.
"""xai_energy_balancer.py — Colossus Energy Balancer core (Issues #1, #5)

v1.1.0 changes:
  - Removed hardcoded Termux sys.path hack (broke CI + all non-Termux envs)
  - supabase_utils imported from repo root (portable, CI-safe)
  - _control_loop calls write_cycle_telemetry() every TICK_INTERVAL cycles
  - dispatch_mcp_event emits structured JSON log (grep/Splunk friendly)
  - Package __init__.py markers added
"""

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple
import statistics

# Safe Supabase import — uses NullClient if creds not set (CI safe)
try:
    from supabase_utils import write_completion_memory, get_supabase_client
except ImportError:
    def write_completion_memory(task_id, payload):
        logging.getLogger("ColossusEnergyBalancer").info(
            "Supabase not available: task_id=%s payload=%s", task_id, payload
        )
    def get_supabase_client():
        return None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ColossusEnergyBalancer")

# ── Physical constants ───────────────────────────────────────────────────
GRID_CAPACITY_MVA         = 150.0
MEGAPACK_CAPACITY_MWH     = 560.0
MEGAPACK_MAX_DISCHARGE_MW = 140.0
MEGAPACK_MAX_CHARGE_MW    = 70.0
SOLAR_PEAK_MW             = 12.0
SAFETY_MARGIN             = 0.08
CASCADE_THRESHOLD         = 0.95
CONTROL_INTERVAL_MS       = 100
FORECAST_HORIZON_S        = 45
RACK_COUNT                = 12500
GPUS_PER_RACK             = 16
H100_TDP_WATTS            = 700
RACK_MAX_KW               = H100_TDP_WATTS * GPUS_PER_RACK / 1000
TICK_INTERVAL_BALANCER    = 10  # run telemetry every N control cycles


class GridMode(Enum):
    NORMAL             = "normal"
    PEAK_SHAVING       = "peak_shaving"
    FREQUENCY_REGULATION = "frequency_regulation"
    BLACK_START        = "black_start"
    DEMAND_RESPONSE    = "demand_response"
    EMERGENCY_SHED     = "emergency_shed"


class MegapackMode(Enum):
    IDLE               = "idle"
    CHARGING           = "charging"
    DISCHARGING        = "discharging"
    FREQUENCY_RESPONSE = "frequency_response"
    RESERVE            = "reserve"


@dataclass
class RackPowerState:
    rack_id: str
    zone: str
    row: int
    current_draw_kw: float
    max_capacity_kw: float = RACK_MAX_KW
    gpu_utilization: float = 0.0
    thermal_headroom_c: float = 15.0
    jobs_active: int = 0
    last_updated: float = field(default_factory=time.time)

    @property
    def available_headroom_kw(self) -> float:
        thermal_limit = self.max_capacity_kw * (self.thermal_headroom_c / 30.0)
        return min(self.max_capacity_kw - self.current_draw_kw, thermal_limit)

    @property
    def utilization_pct(self) -> float:
        return (self.current_draw_kw / self.max_capacity_kw) * 100


@dataclass
class GridState:
    timestamp: float
    grid_draw_mva: float
    grid_frequency_hz: float = 60.0
    voltage_pu: float = 1.0
    megapack_soc_pct: float = 80.0
    megapack_mode: MegapackMode = MegapackMode.IDLE
    megapack_power_mw: float = 0.0
    solar_output_mw: float = 0.0
    grid_mode: GridMode = GridMode.NORMAL
    active_alarms: List[str] = field(default_factory=list)

    @property
    def net_facility_load_mw(self) -> float:
        return self.grid_draw_mva - self.megapack_power_mw - self.solar_output_mw

    @property
    def headroom_mw(self) -> float:
        return (GRID_CAPACITY_MVA * (1 - SAFETY_MARGIN)) - self.net_facility_load_mw


@dataclass
class DemandForecast:
    horizon_seconds: int
    predicted_mw: List[float]
    confidence: float
    peak_predicted_mw: float
    peak_at_seconds: int
    recommendation: str


class MegapackOrchestrator:
    def __init__(self):
        self.soc_pct = 80.0
        self.mode = MegapackMode.IDLE
        self.current_power_mw = 0.0
        self.cycle_count = 0
        self._frequency_response_armed = True
        logger.info("Megapack online: %s MWh / %s MW",
                    MEGAPACK_CAPACITY_MWH, MEGAPACK_MAX_DISCHARGE_MW)

    def available_energy_mwh(self) -> float:
        return MEGAPACK_CAPACITY_MWH * (self.soc_pct / 100.0) * 0.923

    def available_discharge_mw(self) -> float:
        if self.soc_pct < 10.0:
            return 0.0
        return min(MEGAPACK_MAX_DISCHARGE_MW, self.available_energy_mwh() * 6)

    def frequency_response(self, freq_hz: float) -> float:
        if not self._frequency_response_armed:
            return 0.0
        deviation = 60.0 - freq_hz
        if abs(deviation) < 0.05:
            return 0.0
        response_mw = min(50.0, abs(deviation) * 250)
        if deviation > 0:
            actual = min(response_mw, self.available_discharge_mw())
            self.current_power_mw = actual
            self.mode = MegapackMode.FREQUENCY_RESPONSE
            return actual
        else:
            actual = min(response_mw, MEGAPACK_MAX_CHARGE_MW)
            self.current_power_mw = -actual
            self.mode = MegapackMode.FREQUENCY_RESPONSE
            return -actual

    def peak_shave(self, excess_mw: float) -> float:
        dispatch = min(excess_mw, self.available_discharge_mw())
        self.current_power_mw = dispatch
        self.mode = MegapackMode.DISCHARGING
        logger.info("Megapack peak shave: %.1f MW dispatched (SOC: %.1f%%)",
                    dispatch, self.soc_pct)
        return dispatch

    def charge_from_solar(self, solar_surplus_mw: float) -> float:
        if self.soc_pct >= 95.0:
            return 0.0
        absorb = min(solar_surplus_mw, MEGAPACK_MAX_CHARGE_MW)
        self.current_power_mw = -absorb
        self.mode = MegapackMode.CHARGING
        return absorb

    def update_soc(self, interval_hours: float):
        energy_delta_mwh = self.current_power_mw * interval_hours
        self.soc_pct -= (energy_delta_mwh / MEGAPACK_CAPACITY_MWH) * 100
        self.soc_pct = max(5.0, min(100.0, self.soc_pct))


class DemandForecaster:
    def __init__(self, horizon_s: int = FORECAST_HORIZON_S):
        self.horizon_s = horizon_s
        self._history: List[Tuple[float, float]] = []
        self._job_queue_signal: float = 0.0

    def record(self, timestamp: float, demand_mw: float):
        self._history.append((timestamp, demand_mw))
        cutoff = timestamp - 300
        self._history = [(t, v) for t, v in self._history if t >= cutoff]

    def set_job_queue_signal(self, pending_jobs_mw_equivalent: float):
        self._job_queue_signal = pending_jobs_mw_equivalent

    def forecast(self) -> DemandForecast:
        if len(self._history) < 10:
            current = self._history[-1][1] if self._history else 120.0
            flat = [current] * self.horizon_s
            return DemandForecast(
                horizon_seconds=self.horizon_s,
                predicted_mw=flat,
                confidence=0.3,
                peak_predicted_mw=current,
                peak_at_seconds=0,
                recommendation="Insufficient history - holding current allocation",
            )
        values = [v for _, v in self._history[-60:]]
        trend = 0.0
        if len(values) >= 2:
            trend = (values[-1] - values[0]) / len(values)
        current = values[-1]
        predicted = []
        for i in range(self.horizon_s):
            base = current + trend * i
            job_ramp = (
                self._job_queue_signal
                * math.log1p(i)
                / math.log1p(self.horizon_s)
            )
            predicted.append(max(0, base + job_ramp))
        peak_mw = max(predicted)
        peak_at = predicted.index(peak_mw)
        confidence = min(0.95, 0.5 + len(self._history) / 600)
        if peak_mw > GRID_CAPACITY_MVA * CASCADE_THRESHOLD:
            rec = (
                f"CASCADE RISK: Peak {peak_mw:.1f} MW predicted at T+{peak_at}s"
                " - pre-shed recommended"
            )
        elif peak_mw > GRID_CAPACITY_MVA * (1 - SAFETY_MARGIN):
            rec = (
                f"Megapack pre-dispatch recommended: "
                f"{peak_mw - GRID_CAPACITY_MVA*(1-SAFETY_MARGIN):.1f} MW at T+{peak_at}s"
            )
        else:
            rec = "Normal operation - no intervention required"
        return DemandForecast(
            horizon_seconds=self.horizon_s,
            predicted_mw=predicted,
            confidence=confidence,
            peak_predicted_mw=peak_mw,
            peak_at_seconds=peak_at,
            recommendation=rec,
        )


class ZoneController:
    def __init__(self, zone_id: str, capacity_mva: float = 50.0):
        self.zone_id = zone_id
        self.capacity_mva = capacity_mva
        self.racks: Dict[str, RackPowerState] = {}

    def register_rack(self, rack: RackPowerState):
        self.racks[rack.rack_id] = rack

    def total_draw_kw(self) -> float:
        return sum(r.current_draw_kw for r in self.racks.values())

    def utilization_pct(self) -> float:
        return (self.total_draw_kw() / 1000) / self.capacity_mva * 100

    def available_headroom_kw(self) -> float:
        capacity_kw = self.capacity_mva * 1000 * (1 - SAFETY_MARGIN)
        return capacity_kw - self.total_draw_kw()

    def shed_load(self, shed_mw: float) -> float:
        shed_kw_target = shed_mw * 1000 / 3
        shed_kw_actual = 0.0
        for rack in sorted(self.racks.values(), key=lambda r: r.jobs_active):
            if shed_kw_actual >= shed_kw_target:
                break
            available = min(
                rack.current_draw_kw * 0.3,
                shed_kw_target - shed_kw_actual,
            )
            rack.current_draw_kw -= available
            shed_kw_actual += available
        logger.warning("Zone %s shed %.1f kW", self.zone_id, shed_kw_actual)
        return shed_kw_actual / 1000


class ColossusEnergyBalancer:
    def __init__(
        self,
        grid_capacity_mva: float = GRID_CAPACITY_MVA,
        megapack_capacity_mwh: float = MEGAPACK_CAPACITY_MWH,
        safety_margin: float = SAFETY_MARGIN,
        response_interval_ms: int = CONTROL_INTERVAL_MS,
        sb=None,  # Supabase client (None → NullClient via supabase_utils)
    ):
        self.grid_capacity_mva = grid_capacity_mva
        self.safety_margin = safety_margin
        self.response_interval_ms = response_interval_ms
        self.soft_limit_mw = grid_capacity_mva * (1 - safety_margin)
        self.cascade_limit_mw = grid_capacity_mva * CASCADE_THRESHOLD
        self.megapack = MegapackOrchestrator()
        self.forecaster = DemandForecaster()
        self.zones: Dict[str, ZoneController] = {
            "A": ZoneController("A"),
            "B": ZoneController("B"),
            "C": ZoneController("C"),
        }
        self.grid_state = GridState(timestamp=time.time(), grid_draw_mva=0.0)
        self._running = False
        self._cycle_count = 0
        self._total_energy_mwh = 0.0
        self._alarms: List[str] = []
        # Supabase — use provided client or bootstrap from env
        self._sb = sb if sb is not None else get_supabase_client()
        self.mcp_client = None

    # ------------------------------------------------------------------
    # MCP event dispatch
    # ------------------------------------------------------------------

    def dispatch_mcp_event(self, event_type: str, payload: Dict) -> None:
        """Emit a structured MCP event. Logs JSON for grep/Splunk pickup."""
        event = {
            "event_type": event_type,
            "ts": time.time(),
            "payload": payload,
        }
        logger.info("MCP_DISPATCH %s", json.dumps(event))
        if self.mcp_client is not None:
            try:
                self.mcp_client.dispatch(event)
            except Exception as exc:
                logger.error("MCP dispatch failed: %s", exc)

    # ------------------------------------------------------------------
    # Telemetry — write PUE row to Supabase each cycle
    # ------------------------------------------------------------------

    def write_cycle_telemetry(self) -> None:
        """Compute PUE and write one energy_telemetry row per balance cycle."""
        it_kw     = self.compute_total_draw_mw() * 1000.0
        cooling_kw = it_kw * 0.35
        pdu_kw    = it_kw * 0.04
        total_kw  = it_kw + cooling_kw + pdu_kw
        pue       = total_kw / max(1.0, it_kw)
        import uuid
        row = {
            "id":         str(uuid.uuid4()),
            "ts":         time.time(),
            "pue":        round(pue, 4),
            "total_kw":   round(total_kw, 1),
            "it_load_kw": round(it_kw, 1),
            "cooling_kw": round(cooling_kw, 1),
            "zone":       "all",
        }
        try:
            self._sb.table("energy_telemetry").insert(row).execute()
        except Exception as exc:
            logger.error("energy_telemetry write failed: %s", exc)

    # ------------------------------------------------------------------
    # Core balancer methods
    # ------------------------------------------------------------------

    def ingest_telemetry(self, rack_telemetry: List[Dict]) -> None:
        for data in rack_telemetry:
            zone_id = data.get("zone", "A")
            rack_id = data.get("rack_id")
            if not rack_id:
                continue
            rack = self.zones[zone_id].racks.get(rack_id)
            if rack:
                rack.current_draw_kw      = data.get("draw_kw",           rack.current_draw_kw)
                rack.gpu_utilization      = data.get("gpu_util",           rack.gpu_utilization)
                rack.thermal_headroom_c   = data.get("thermal_headroom_c", rack.thermal_headroom_c)
                rack.jobs_active          = data.get("jobs_active",        rack.jobs_active)
                rack.last_updated         = time.time()

    def compute_total_draw_mw(self) -> float:
        return sum(z.total_draw_kw() for z in self.zones.values()) / 1000

    def _execute_control_action(self, mode: GridMode, total_mw: float) -> None:
        if mode == GridMode.EMERGENCY_SHED:
            excess = total_mw - self.soft_limit_mw
            shed_total = sum(zone.shed_load(excess / 3) for zone in self.zones.values())
            self.dispatch_mcp_event("zone_overload", {"shed_mw": round(shed_total, 3)})
            logger.error("EMERGENCY SHED: %.1f MW shed", shed_total)
            self._alarms.append(
                f"EMERGENCY_SHED:{total_mw:.1f}MW@{datetime.now().isoformat()}"
            )

    async def _control_loop(self) -> None:
        while self._running:
            self._cycle_count += 1
            if self._cycle_count % TICK_INTERVAL_BALANCER == 0:
                total_mw = self.compute_total_draw_mw()
                mode = GridMode.NORMAL
                self._execute_control_action(mode, total_mw)
                # Issue #5 fix: write telemetry every tick, not just at boot
                self.write_cycle_telemetry()
            await asyncio.sleep(CONTROL_INTERVAL_MS / 1000)

    def run_continuous(self) -> None:
        self._running = True
        logger.info("ColossusEnergyBalancer starting continuous operation...")
        try:
            write_completion_memory(
                "ISSUE_5",
                {"status": "implemented", "tick_interval": TICK_INTERVAL_BALANCER},
            )
        except Exception as exc:
            logger.warning("Supabase boot write skipped: %s", exc)
        asyncio.run(self._control_loop())
