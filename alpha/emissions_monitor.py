# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
#!/usr/bin/env python3
"""
COLOSSUS EMISSIONS COMPLIANCE MONITOR

Continuous monitoring of turbine emissions to prevent Clean Air Act violations.

Legal context (Memphis/Southaven Colossus 1):
  - EarthJustice complaint: 18 unpermitted Caterpillar turbines, ~200 MW total
  - Mississippi DEQ / EPA Region 4 enforcement risk
  - Title V major source threshold: >100 tons/year NOx or PM2.5
  - xAI must either: (a) obtain Title V permit, or (b) cap operations below threshold

This module tracks:
  - Per-turbine runtime hours (daily, monthly, annual)
  - Estimated NOx/PM2.5/CO2 emissions based on turbine capacity + BACT emission factors
  - Threshold proximity alerts
  - Automatic curtailment recommendations

Emission factors (conservative, Caterpillar G3520 class @ ~11 MW each):
  NOx:  2.0 g/kWh  (0.0044 lb/kWh)
  PM2.5: 0.05 g/kWh
  CO2:  450 g/kWh  (0.992 lb/kWh)
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("COLOSSUS.EMISSIONS")

# Clean Air Act thresholds (tons/year) for major source status
TITLE_V_MAJOR_SOURCE_TONS = {
    "NOx":   100.0,
    "PM2.5":  25.0,
    "CO2":  25000.0,
}

# Emission factors g/kWh (Caterpillar G3520C at rated load)
EMISSION_FACTORS_G_PER_KWH = {
    "NOx":   2.0,
    "PM2.5": 0.05,
    "CO2":   450.0,
}

KG_PER_TON = 907.185


@dataclass
class TurbineUnit:
    turbine_id:     str
    capacity_kw:    float     # nameplate kW
    runtime_hrs:    float = 0.0
    energy_kwh:     float = 0.0  # cumulative this year
    load_factor:    float = 0.85  # typical operating load factor

    def add_runtime(self, hours: float):
        self.runtime_hrs += hours
        self.energy_kwh  += hours * self.capacity_kw * self.load_factor

    def emissions_tons(self, pollutant: str) -> float:
        """Cumulative tons of pollutant emitted this tracking period."""
        factor_g = EMISSION_FACTORS_G_PER_KWH.get(pollutant, 0.0)
        grams = self.energy_kwh * factor_g
        return grams / (KG_PER_TON * 1000)


@dataclass
class EmissionsAlert:
    timestamp:   float
    turbine_id:  str
    pollutant:   str
    current_tons: float
    threshold_tons: float
    pct_of_threshold: float
    level:       str   # "WARNING" | "CRITICAL" | "VIOLATION"
    action:      str


class EmissionsMonitor:
    """
    Tracks a fleet of turbine units and fires alerts when emissions
    approach or exceed Clean Air Act permit thresholds.
    """

    WARNING_PCT  = 0.70   # alert at 70% of threshold
    CRITICAL_PCT = 0.90   # alert at 90%

    def __init__(self, turbines: List[TurbineUnit]):
        self.turbines: Dict[str, TurbineUnit] = {t.turbine_id: t for t in turbines}
        self.alerts: List[EmissionsAlert] = []

    def record_runtime(self, turbine_id: str, hours: float):
        if turbine_id not in self.turbines:
            raise KeyError(f"Unknown turbine: {turbine_id}")
        self.turbines[turbine_id].add_runtime(hours)
        self._check_thresholds(turbine_id)

    def fleet_totals(self) -> Dict[str, float]:
        """Aggregate emissions across all turbines (tons/year-to-date)."""
        totals: Dict[str, float] = {p: 0.0 for p in EMISSION_FACTORS_G_PER_KWH}
        for t in self.turbines.values():
            for p in totals:
                totals[p] += t.emissions_tons(p)
        return {p: round(v, 4) for p, v in totals.items()}

    def compliance_status(self) -> Dict[str, str]:
        """Per-pollutant compliance status."""
        totals = self.fleet_totals()
        status = {}
        for p, threshold in TITLE_V_MAJOR_SOURCE_TONS.items():
            pct = totals.get(p, 0) / threshold
            if pct >= 1.0:
                status[p] = "VIOLATION"
            elif pct >= self.CRITICAL_PCT:
                status[p] = "CRITICAL"
            elif pct >= self.WARNING_PCT:
                status[p] = "WARNING"
            else:
                status[p] = "OK"
        return status

    def turbine_can_run(self, turbine_id: str, add_hours: float = 1.0) -> Tuple[bool, str]:
        """
        Pre-flight check: can this turbine run for `add_hours` more hours
        without pushing any pollutant over the threshold?
        """
        t = self.turbines.get(turbine_id)
        if not t:
            return False, "Unknown turbine"
        for p, threshold in TITLE_V_MAJOR_SOURCE_TONS.items():
            projected = t.emissions_tons(p) + (
                add_hours * t.capacity_kw * t.load_factor
                * EMISSION_FACTORS_G_PER_KWH[p] / (KG_PER_TON * 1000)
            )
            if projected >= threshold:
                return False, f"Would exceed {p} threshold ({projected:.2f} >= {threshold} tons)"
        return True, "OK"

    def _check_thresholds(self, turbine_id: str):
        t = self.turbines[turbine_id]
        for p, threshold in TITLE_V_MAJOR_SOURCE_TONS.items():
            current = t.emissions_tons(p)
            pct = current / threshold
            if pct >= 1.0:
                level = "VIOLATION"
                action = f"IMMEDIATE: shut down turbine {turbine_id}, notify MDEQ/EPA within 24h"
            elif pct >= self.CRITICAL_PCT:
                level = "CRITICAL"
                action = f"Curtail turbine {turbine_id} to stay below {p} threshold"
            elif pct >= self.WARNING_PCT:
                level = "WARNING"
                action = f"Plan curtailment schedule for {turbine_id}"
            else:
                continue

            alert = EmissionsAlert(
                timestamp=time.time(),
                turbine_id=turbine_id,
                pollutant=p,
                current_tons=round(current, 4),
                threshold_tons=threshold,
                pct_of_threshold=round(pct * 100, 1),
                level=level,
                action=action,
            )
            self.alerts.append(alert)
            logger.warning("[EMISSIONS %s] %s %s: %.1f%% of threshold — %s",
                           level, turbine_id, p, pct * 100, action)

    def Tuple(self, *args):
        return tuple(args)


from typing import Tuple  # noqa: E402  (re-import for type hints)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    # Simulate 18 Colossus turbines at ~11 MW each (Memphis configuration)
    turbines = [TurbineUnit(turbine_id=f"TRB-{i:02d}", capacity_kw=11_000) for i in range(18)]
    monitor = EmissionsMonitor(turbines)

    # Simulate 5,000 hours of operation distributed across all turbines
    for t_id in [f"TRB-{i:02d}" for i in range(18)]:
        monitor.record_runtime(t_id, 278)  # ~278h each = 5000h total fleet

    print("\nFleet emissions totals (tons YTD):")
    for p, v in monitor.fleet_totals().items():
        threshold = TITLE_V_MAJOR_SOURCE_TONS.get(p, "N/A")
        pct = v / threshold * 100 if isinstance(threshold, float) else 0
        print(f"  {p:<6}: {v:>10.2f} tons  (threshold {threshold} tons, {pct:.1f}% used)")

    print("\nCompliance status:")
    for p, s in monitor.compliance_status().items():
        print(f"  {p:<6}: {s}")

    # Check if TRB-00 can run another 100 hours
    ok, reason = monitor.turbine_can_run("TRB-00", add_hours=100)
    print(f"\nCan TRB-00 run 100 more hours? {ok} — {reason}")
