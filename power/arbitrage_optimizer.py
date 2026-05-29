#!/usr/bin/env python3
"""
COLOSSUS POWER ARBITRAGE OPTIMIZER

Dynamically shifts compute load across time windows to:
  1. Minimize electricity cost by chasing off-peak MISO LMP prices
  2. Maximize renewable utilization (wind overnight, solar midday)
  3. Reduce grid stress during MISO peak demand windows (2-7pm CDT)
  4. Earn demand response credits from TVA/MLGW curtailment programs

Architecture note:
  Colossus 1: ~200 MW draw, mixed H100/H200 racks, Memphis/Southaven
  Colossus 2: targets 1 GW+; this optimizer is designed for that scale.
  At 1 GW, a 10% load shift saves ~$20M/year at $0.06/kWh average.

Inputs:
  - Real-time MISO LMP feed (hourly day-ahead + 5-min real-time)
  - On-site battery SOC (target: 30-min ride-through = ~500 MWh at 1GW)
  - Renewable forecast (wind/solar 24h ahead)
  - Job priority queue (training > fine-tuning > inference)
  - Turbine runtime tracker (for Clean Air Act hourly limits)
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import math

logger = logging.getLogger("COLOSSUS.POWER_ARBITRAGE")


class JobPriority(Enum):
    TRAINING_GROK   = 1  # highest: Grok training runs, never shed
    FINE_TUNING     = 2
    BATCH_INFERENCE = 3
    API_INFERENCE   = 4  # lowest sheddable (SLA allows 200ms delay)


@dataclass
class PowerWindow:
    """One hour of power planning."""
    hour_utc:          int          # 0-23
    lmp_cents_per_kwh: float        # MISO Locational Marginal Price
    wind_mw:           float        # forecast wind generation available
    solar_mw:          float        # forecast solar generation available
    battery_soc_mwh:   float        # state of charge at start of window
    grid_demand_pct:   float        # 0-100, MISO demand as % of peak
    turbine_hrs_used:  float        # cumulative turbine-hours this calendar day


@dataclass
class LoadTarget:
    hour_utc: int
    target_mw: float
    renewable_fraction: float
    battery_delta_mwh: float   # positive = charging, negative = discharging
    turbine_mw: float
    cost_estimate_usd: float
    shed_jobs: List[JobPriority] = field(default_factory=list)
    notes: str = ""


class PowerArbitrageOptimizer:
    """
    Given a 24-hour power window forecast, produce an optimized
    load schedule that minimizes cost and regulatory risk.
    """

    # Colossus 2 design parameters
    DESIGN_LOAD_MW       = 1000.0   # 1 GW nameplate
    MIN_LOAD_MW          = 400.0    # can't drop below this (cooling floors)
    BATTERY_CAPACITY_MWH = 500.0    # 30-min ride-through at full load
    BATTERY_MAX_RATE_MW  = 250.0    # charge/discharge rate limit
    BATTERY_EFFICIENCY   = 0.92     # round-trip

    # Emissions guard: turbines must not exceed 8,760 hrs/yr to stay
    # below Title V major source threshold (Memphis consent order context)
    TURBINE_MAX_HRS_PER_DAY = 16.0
    TURBINE_CAPACITY_MW      = 400.0

    # Cost thresholds (cents/kWh)
    LMP_PEAK_THRESHOLD    = 8.0   # above this: shed non-critical load
    LMP_OFFPEAK_THRESHOLD = 3.0   # below this: charge battery, run heavy jobs
    LMP_SPIKE_THRESHOLD   = 15.0  # above this: emergency load shed

    def optimize(self, windows: List[PowerWindow]) -> List[LoadTarget]:
        targets: List[LoadTarget] = []
        battery_soc = windows[0].battery_soc_mwh if windows else self.BATTERY_CAPACITY_MWH * 0.8
        turbine_hrs_today = windows[0].turbine_hrs_used if windows else 0.0

        for w in windows:
            target = self._plan_window(w, battery_soc, turbine_hrs_today)
            battery_soc = max(0, min(self.BATTERY_CAPACITY_MWH,
                                     battery_soc - target.battery_delta_mwh))
            if target.turbine_mw > 0:
                turbine_hrs_today += 1.0
            targets.append(target)

        return targets

    def _plan_window(
        self,
        w: PowerWindow,
        battery_soc: float,
        turbine_hrs: float,
    ) -> LoadTarget:
        renewable_avail = w.wind_mw + w.solar_mw
        shed_jobs: List[JobPriority] = []
        notes_parts: List[str] = []

        # Base: try to run at full design load
        target_mw = self.DESIGN_LOAD_MW

        # --- Grid stress check ---
        if w.grid_demand_pct > 90:
            # MISO near-peak: shed batch + API inference
            target_mw -= 150.0
            shed_jobs += [JobPriority.BATCH_INFERENCE, JobPriority.API_INFERENCE]
            notes_parts.append("Grid>90%: shed batch+API inference")

        # --- LMP-based load shifting ---
        if w.lmp_cents_per_kwh >= self.LMP_SPIKE_THRESHOLD:
            target_mw = self.MIN_LOAD_MW
            shed_jobs = [j for j in JobPriority if j != JobPriority.TRAINING_GROK]
            notes_parts.append(f"LMP spike {w.lmp_cents_per_kwh:.1f}c: emergency shed")
        elif w.lmp_cents_per_kwh >= self.LMP_PEAK_THRESHOLD:
            target_mw = min(target_mw, 750.0)
            if JobPriority.API_INFERENCE not in shed_jobs:
                shed_jobs.append(JobPriority.API_INFERENCE)
            notes_parts.append(f"LMP high {w.lmp_cents_per_kwh:.1f}c: reduce load")
        elif w.lmp_cents_per_kwh <= self.LMP_OFFPEAK_THRESHOLD:
            # Off-peak: charge battery if room
            notes_parts.append(f"LMP low {w.lmp_cents_per_kwh:.1f}c: run full + charge battery")

        target_mw = max(self.MIN_LOAD_MW, target_mw)

        # --- Battery dispatch ---
        grid_need = target_mw - renewable_avail
        battery_delta = 0.0
        if w.lmp_cents_per_kwh <= self.LMP_OFFPEAK_THRESHOLD:
            # Charge during cheap windows
            charge_room = self.BATTERY_CAPACITY_MWH - battery_soc
            charge_rate = min(self.BATTERY_MAX_RATE_MW, charge_room / self.BATTERY_EFFICIENCY)
            battery_delta = charge_rate  # positive = charging
        elif w.lmp_cents_per_kwh >= self.LMP_PEAK_THRESHOLD and battery_soc > 50:
            # Discharge to offset grid draw during expensive windows
            discharge = min(self.BATTERY_MAX_RATE_MW, battery_soc * 0.5)
            grid_need -= discharge
            battery_delta = -discharge  # negative = discharging
            notes_parts.append(f"Battery discharge {discharge:.0f}MWh to offset peak")

        # --- Turbine guard (emissions compliance) ---
        turbine_mw = 0.0
        remaining_hrs = self.TURBINE_MAX_HRS_PER_DAY - turbine_hrs
        if remaining_hrs > 0 and grid_need > renewable_avail:
            gap = max(0, target_mw - renewable_avail - abs(min(0, battery_delta)))
            turbine_mw = min(gap, self.TURBINE_CAPACITY_MW)
            if turbine_hrs >= self.TURBINE_MAX_HRS_PER_DAY:
                turbine_mw = 0.0
                notes_parts.append("TURBINE CAPPED: daily limit reached, grid-only")

        renewable_frac = min(1.0, renewable_avail / max(1, target_mw))

        cost = (target_mw * 1000) * (w.lmp_cents_per_kwh / 100)  # USD for this MWh window

        return LoadTarget(
            hour_utc=w.hour_utc,
            target_mw=round(target_mw, 1),
            renewable_fraction=round(renewable_frac, 3),
            battery_delta_mwh=round(battery_delta, 1),
            turbine_mw=round(turbine_mw, 1),
            cost_estimate_usd=round(cost, 2),
            shed_jobs=shed_jobs,
            notes="; ".join(notes_parts),
        )

    def daily_summary(self, targets: List[LoadTarget]) -> Dict:
        total_cost = sum(t.cost_estimate_usd for t in targets)
        avg_renewable = sum(t.renewable_fraction for t in targets) / max(1, len(targets))
        turbine_hours = sum(1 for t in targets if t.turbine_mw > 0)
        return {
            "total_cost_usd":     round(total_cost, 2),
            "avg_renewable_frac": round(avg_renewable, 3),
            "turbine_hours":      turbine_hours,
            "turbine_compliant":  turbine_hours <= self.TURBINE_MAX_HRS_PER_DAY,
            "hours_shedding":     sum(1 for t in targets if t.shed_jobs),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    # Synthetic 24h day: overnight cheap wind, afternoon solar, evening peak
    windows = []
    for h in range(24):
        lmp = 2.5 if h < 6 else (12.0 if 14 <= h <= 19 else 5.5)
        wind = 300 if h < 8 or h >= 20 else 80
        solar = 0 if h < 6 or h >= 20 else (350 if 10 <= h <= 15 else 150)
        grid_demand = 60 if h < 7 else (92 if 15 <= h <= 18 else 75)
        windows.append(PowerWindow(
            hour_utc=h, lmp_cents_per_kwh=lmp,
            wind_mw=wind, solar_mw=solar,
            battery_soc_mwh=400.0,
            grid_demand_pct=grid_demand,
            turbine_hrs_used=0.0,
        ))

    optimizer = PowerArbitrageOptimizer()
    targets = optimizer.optimize(windows)
    summary = optimizer.daily_summary(targets)

    print(f"{'Hour':>4} {'Load MW':>8} {'Renew%':>7} {'Turbine MW':>10} {'Cost $':>10} Notes")
    print("-" * 80)
    for t in targets:
        print(f"{t.hour_utc:>4} {t.target_mw:>8.0f} {t.renewable_fraction*100:>7.1f}% {t.turbine_mw:>10.0f} {t.cost_estimate_usd:>10.2f} {t.notes[:50]}")
    print()
    print("DAILY SUMMARY:", summary)
