"""
xAI Colossus Energy Balancer
Real-time GPU load balancing and grid power orchestration
for 150 MVA / 200,000+ H100 GPU facility

Architecture:
- 100ms control loop for per-rack power telemetry
- Predictive demand forecasting (45-second lookahead)
- Tesla Megapack buffer orchestration
- Thermal-power co-optimization with cooling system
- NUMA-aware workload allocation
- Cascade protection and automatic load shedding
"""

import asyncio
import time
import json
import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
from datetime import datetime
import statistics

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('ColossusEnergyBalancer')

GRID_CAPACITY_MVA = 150.0
MEGAPACK_CAPACITY_MWH = 560.0
MEGAPACK_MAX_DISCHARGE_MW = 140.0
MEGAPACK_MAX_CHARGE_MW = 70.0
SOLAR_PEAK_MW = 12.0
SAFETY_MARGIN = 0.08
CASCADE_THRESHOLD = 0.95
CONTROL_INTERVAL_MS = 100
FORECAST_HORIZON_S = 45
RACK_COUNT = 12500
GPUS_PER_RACK = 16
H100_TDP_WATTS = 700
RACK_MAX_KW = H100_TDP_WATTS * GPUS_PER_RACK / 1000


class GridMode(Enum):
    NORMAL = "normal"
    PEAK_SHAVING = "peak_shaving"
    FREQUENCY_REGULATION = "frequency_regulation"
    BLACK_START = "black_start"
    DEMAND_RESPONSE = "demand_response"
    EMERGENCY_SHED = "emergency_shed"


class MegapackMode(Enum):
    IDLE = "idle"
    CHARGING = "charging"
    DISCHARGING = "discharging"
    FREQUENCY_RESPONSE = "frequency_response"
    RESERVE = "reserve"


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
    """Controls Tesla Megapack array - 560 MWh / 140 MW discharge capacity."""

    def __init__(self):
        self.soc_pct = 80.0
        self.mode = MegapackMode.IDLE
        self.current_power_mw = 0.0
        self.cycle_count = 0
        self._frequency_response_armed = True
        logger.info(f"Megapack online: {MEGAPACK_CAPACITY_MWH} MWh / {MEGAPACK_MAX_DISCHARGE_MW} MW")

    def available_energy_mwh(self) -> float:
        return MEGAPACK_CAPACITY_MWH * (self.soc_pct / 100.0) * 0.923

    def available_discharge_mw(self) -> float:
        if self.soc_pct < 10.0:
            return 0.0
        return min(MEGAPACK_MAX_DISCHARGE_MW, self.available_energy_mwh() * 6)

    def frequency_response(self, freq_hz: float) -> float:
        """Sub-100ms frequency regulation response."""
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
        logger.info(f"Megapack peak shave: {dispatch:.1f} MW dispatched (SOC: {self.soc_pct:.1f}%)")
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
    """45-second predictive demand forecasting using rolling telemetry."""

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
                recommendation="Insufficient history - holding current allocation"
            )
        values = [v for _, v in self._history[-60:]]
        trend = 0.0
        if len(values) >= 2:
            trend = (values[-1] - values[0]) / len(values)
        current = values[-1]
        predicted = []
        for i in range(self.horizon_s):
            base = current + trend * i
            job_ramp = self._job_queue_signal * math.log1p(i) / math.log1p(self.horizon_s)
            predicted.append(max(0, base + job_ramp))
        peak_mw = max(predicted)
        peak_at = predicted.index(peak_mw)
        confidence = min(0.95, 0.5 + len(self._history) / 600)
        if peak_mw > GRID_CAPACITY_MVA * CASCADE_THRESHOLD:
            rec = f"CASCADE RISK: Peak {peak_mw:.1f} MW predicted at T+{peak_at}s - pre-shed recommended"
        elif peak_mw > GRID_CAPACITY_MVA * (1 - SAFETY_MARGIN):
            rec = f"Megapack pre-dispatch recommended: {peak_mw - GRID_CAPACITY_MVA*(1-SAFETY_MARGIN):.1f} MW at T+{peak_at}s"
        else:
            rec = "Normal operation - no intervention required"
        return DemandForecast(
            horizon_seconds=self.horizon_s,
            predicted_mw=predicted,
            confidence=confidence,
            peak_predicted_mw=peak_mw,
            peak_at_seconds=peak_at,
            recommendation=rec
        )


class ZoneController:
    """Manages one of three 50 MVA distribution zones (A, B, C)."""

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

    def get_best_racks_for_workload(self, required_kw: float) -> List[RackPowerState]:
        eligible = [
            r for r in self.racks.values()
            if r.available_headroom_kw >= required_kw / max(1, len(self.racks))
            and r.thermal_headroom_c > 5.0
        ]
        return sorted(eligible, key=lambda r: r.available_headroom_kw, reverse=True)

    def shed_load(self, shed_mw: float) -> float:
        shed_kw_target = shed_mw * 1000 / 3
        shed_kw_actual = 0.0
        for rack in sorted(self.racks.values(), key=lambda r: r.jobs_active):
            if shed_kw_actual >= shed_kw_target:
                break
            available = min(rack.current_draw_kw * 0.3, shed_kw_target - shed_kw_actual)
            rack.current_draw_kw -= available
            shed_kw_actual += available
        logger.warning(f"Zone {self.zone_id} shed {shed_kw_actual:.1f} kW")
        return shed_kw_actual / 1000


class ColossusEnergyBalancer:
    """
    Primary energy orchestration engine for xAI Colossus.
    Runs at 100ms intervals, coordinates all power systems.
    """

    def __init__(
        self,
        grid_capacity_mva: float = GRID_CAPACITY_MVA,
        megapack_capacity_mwh: float = MEGAPACK_CAPACITY_MWH,
        safety_margin: float = SAFETY_MARGIN,
        response_interval_ms: int = CONTROL_INTERVAL_MS
    ):
        self.grid_capacity_mva = grid_capacity_mva
        self.safety_margin = safety_margin
        self.response_interval_ms = response_interval_ms
        self.soft_limit_mw = grid_capacity_mva * (1 - safety_margin)
        self.cascade_limit_mw = grid_capacity_mva * CASCADE_THRESHOLD
        self.megapack = MegapackOrchestrator()
        self.forecaster = DemandForecaster()
        self.zones: Dict[str, ZoneController] = {
            'A': ZoneController('A'),
            'B': ZoneController('B'),
            'C': ZoneController('C')
        }
        self.grid_state = GridState(timestamp=time.time(), grid_draw_mva=0.0)
        self._running = False
        self._cycle_count = 0
        self._total_energy_mwh = 0.0
        self._alarms: List[str] = []
        logger.info(
            f"ColossusEnergyBalancer initialized: "
            f"{grid_capacity_mva} MVA / {megapack_capacity_mwh} MWh Megapack / "
            f"{response_interval_ms}ms control loop"
        )

    def ingest_telemetry(self, rack_telemetry: List[Dict]) -> None:
        for data in rack_telemetry:
            zone_id = data.get('zone', 'A')
            rack_id = data.get('rack_id')
            if not rack_id:
                continue
            rack = self.zones[zone_id].racks.get(rack_id)
            if rack:
                rack.current_draw_kw = data.get('draw_kw', rack.current_draw_kw)
                rack.gpu_utilization = data.get('gpu_util', rack.gpu_utilization)
                rack.thermal_headroom_c = data.get('thermal_headroom_c', rack.thermal_headroom_c)
                rack.jobs_active = data.get('jobs_active', rack.jobs_active)
                rack.last_updated = time.time()

    def compute_total_draw_mw(self) -> float:
        return sum(z.total_draw_kw() for z in self.zones.values()) / 1000

    def _check_frequency(self) -> None:
        freq = self.grid_state.grid_frequency_hz
        if abs(freq - 60.0) > 0.05:
            response = self.megapack.frequency_response(freq)
            if response != 0:
                logger.warning(f"Frequency event: {freq:.3f} Hz -> Megapack {response:+.1f} MW")
                self._alarms.append(f"FREQ_EVENT:{freq:.3f}Hz@{datetime.now().isoformat()}")

    def _check_load_limits(self, total_mw: float) -> GridMode:
        if total_mw >= self.cascade_limit_mw:
            return GridMode.EMERGENCY_SHED
        elif total_mw >= self.soft_limit_mw:
            return GridMode.PEAK_SHAVING
        return GridMode.NORMAL

    def _execute_control_action(self, mode: GridMode, total_mw: float) -> None:
        if mode == GridMode.EMERGENCY_SHED:
            excess = total_mw - self.soft_limit_mw
            shed_total = 0.0
            for zone in self.zones.values():
                shed_total += zone.shed_load(excess / 3)
            logger.error(f"EMERGENCY SHED: {shed_total:.1f} MW shed across all zones")
            self._alarms.append(f"EMERGENCY_SHED:{total_mw:.1f}MW@{datetime.now().isoformat()}")
        elif mode == GridMode.PEAK_SHAVING:
            excess = total_mw - self.soft_limit_mw
            dispatched = self.megapack.peak_shave(excess)
            if dispatched < excess:
                remaining = excess - dispatched
                for zone in self.zones.values():
                    zone.shed_load(remaining / 3)
        else:
            solar = self.grid_state.solar_output_mw
            headroom = self.soft_limit_mw - total_mw
            if solar > 0 and headroom > 5.0:
                surplus = min(solar, headroom - 5.0)
                self.megapack.charge_from_solar(surplus)

    def _update_grid_state(self, total_mw: float, mode: GridMode) -> None:
        interval_h = self.response_interval_ms / 1000 / 3600
        self._total_energy_mwh += total_mw * interval_h
        self.megapack.update_soc(interval_h)
        self.grid_state = GridState(
            timestamp=time.time(),
            grid_draw_mva=total_mw,
            grid_frequency_hz=self.grid_state.grid_frequency_hz,
            megapack_soc_pct=self.megapack.soc_pct,
            megapack_mode=self.megapack.mode,
            megapack_power_mw=self.megapack.current_power_mw,
            solar_output_mw=self.grid_state.solar_output_mw,
            grid_mode=mode,
            active_alarms=self._alarms[-10:]
        )
        self.forecaster.record(time.time(), total_mw)

    def get_status(self) -> Dict:
        total_mw = self.compute_total_draw_mw()
        forecast = self.forecaster.forecast()
        return {
            'timestamp': datetime.now().isoformat(),
            'cycle': self._cycle_count,
            'grid': {
                'draw_mw': round(total_mw, 2),
                'capacity_mva': self.grid_capacity_mva,
                'utilization_pct': round(total_mw / self.grid_capacity_mva * 100, 1),
                'headroom_mw': round(self.soft_limit_mw - total_mw, 2),
                'frequency_hz': self.grid_state.grid_frequency_hz,
                'mode': self.grid_state.grid_mode.value
            },
            'megapack': {
                'soc_pct': round(self.megapack.soc_pct, 1),
                'power_mw': round(self.megapack.current_power_mw, 1),
                'mode': self.megapack.mode.value,
                'available_mwh': round(self.megapack.available_energy_mwh(), 1),
                'available_discharge_mw': round(self.megapack.available_discharge_mw(), 1)
            },
            'zones': {
                zid: {
                    'draw_mw': round(z.total_draw_kw() / 1000, 2),
                    'utilization_pct': round(z.utilization_pct(), 1),
                    'headroom_kw': round(z.available_headroom_kw(), 1),
                    'rack_count': len(z.racks)
                } for zid, z in self.zones.items()
            },
            'forecast': {
                'peak_mw': round(forecast.peak_predicted_mw, 1),
                'peak_at_s': forecast.peak_at_seconds,
                'confidence': round(forecast.confidence, 2),
                'recommendation': forecast.recommendation
            },
            'totals': {
                'energy_consumed_mwh': round(self._total_energy_mwh, 2),
                'active_alarms': len(self._alarms),
                'total_racks': sum(len(z.racks) for z in self.zones.values())
            }
        }

    async def _control_loop(self) -> None:
        while self._running:
            loop_start = time.monotonic()
            try:
                self._cycle_count += 1
                total_mw = self.compute_total_draw_mw()
                self._check_frequency()
                mode = self._check_load_limits(total_mw)
                self._execute_control_action(mode, total_mw)
                self._update_grid_state(total_mw, mode)
                if self._cycle_count % 100 == 0:
                    status = self.get_status()
                    logger.info(
                        f"[Cycle {self._cycle_count}] "
                        f"Draw: {status['grid']['draw_mw']} MW "
                        f"({status['grid']['utilization_pct']}%) | "
                        f"Megapack SOC: {status['megapack']['soc_pct']}% | "
                        f"Mode: {status['grid']['mode']}"
                    )
            except Exception as e:
                logger.error(f"Control loop error at cycle {self._cycle_count}: {e}")
            elapsed = (time.monotonic() - loop_start) * 1000
            sleep_ms = max(0, self.response_interval_ms - elapsed)
            await asyncio.sleep(sleep_ms / 1000)

    def run_continuous(self) -> None:
        self._running = True
        logger.info("ColossusEnergyBalancer starting continuous operation...")
        asyncio.run(self._control_loop())

    def stop(self) -> None:
        self._running = False
        logger.info(
            f"ColossusEnergyBalancer stopped after {self._cycle_count} cycles, "
            f"{self._total_energy_mwh:.1f} MWh consumed"
        )


if __name__ == '__main__':
    balancer = ColossusEnergyBalancer(
        grid_capacity_mva=150,
        megapack_capacity_mwh=560,
        safety_margin=0.08,
        response_interval_ms=100
    )
    print(json.dumps(balancer.get_status(), indent=2))
