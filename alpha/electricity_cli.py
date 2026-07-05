# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
#!/usr/bin/env python3
"""
ELECTRICITY CLI
Command-line interface for finite power grid management.

Commands:
  grid      - Show real-time grid health
  thermal   - Update GPU temperatures
  constraint - Check power constraints
  cooling   - Predict constraint events
  emergency - Initiate emergency shutdown
  health    - Full system health report

Migrated from GlacierEQ/electricity (now archived).
Canonical home: xai-colossus-energy/electricity/
"""

import sys
import json
import argparse
from datetime import datetime

from .electricity_apex_boot_core import APEXPowerGrid, GridTier, ThermalPowerFeedback
from .electricity_thermal_orchestrator import (
    ElectricityThermalOrchestrator,
    FiniteCoolingBoundary,
    ConstraintMode,
)


class ElectricityCLI:
    """Master CLI for electricity system"""

    def __init__(self):
        self.grids = {
            "standard": APEXPowerGrid(GridTier.STANDARD),
            "colossal": APEXPowerGrid(GridTier.COLOSSAL),
        }
        self.orch = ElectricityThermalOrchestrator(max_power_watts=150000, gpu_capacity=128)
        self.cooling = FiniteCoolingBoundary(cooling_capacity_watts=150000, thermal_tlc_celsius=85)

    def cmd_grid_status(self, args):
        tier = getattr(args, "tier", "standard") or "standard"
        grid = self.grids.get(tier)
        if not grid:
            print(f"ERROR: Unknown tier '{tier}'")
            return 1
        s = grid.grid_status()
        print(f"\n{'='*70}\nELECTRICITY GRID STATUS [{tier.upper()}]\n{'='*70}")
        for k, v in s.items():
            print(f"  {k}: {v}")
        print("="*70)
        return 0

    def cmd_thermal_update(self, args):
        if not args.gpu_id or args.temp is None:
            print("ERROR: --gpu-id and --temp required")
            return 1
        tier = getattr(args, "tier", "standard") or "standard"
        grid = self.grids.get(tier)
        if not grid:
            print(f"ERROR: Unknown tier '{tier}'")
            return 1
        gpu = grid.update_gpu_temp(args.gpu_id, args.temp)
        print(f"\n[THERMAL UPDATE] {args.gpu_id}")
        print(f"  Temp:      {gpu['temp_celsius']:.1f}°C")
        print(f"  Power:     {gpu['power_watts']:.0f}W")
        print(f"  Headroom:  {gpu.get('headroom', 0):.1f}°C")
        print(f"  Throttled: {'YES' if gpu['throttled'] else 'NO'}")
        c = self.orch.update_thermal_state({args.gpu_id: args.temp})
        if c["constraint_mode"] != "normal":
            print(f"  ⚠️  CONSTRAINT: {c['constraint_mode'].upper()} → {c['throttle_action']}")
        return 0

    def cmd_constraint_check(self, args):
        tier = getattr(args, "tier", "standard") or "standard"
        grid = self.grids.get(tier)
        if not grid:
            print(f"ERROR: Unknown tier '{tier}'")
            return 1
        status = grid.grid_status()
        temps = {gid: g["temp_celsius"] for gid, g in grid.gpu_states.items()}
        c = self.orch.update_thermal_state(temps)
        cc = self.cooling.constraint_report(current_power=c["total_power_needed"], current_temp=status["avg_temp_celsius"])
        print(f"\n{'='*70}\nPOWER CONSTRAINT REPORT\n{'='*70}")
        print(f"  Mode:            {c['constraint_mode'].upper()}")
        print(f"  Power needed:    {c['total_power_needed']:.0f}W")
        print(f"  Available:       {c['available_watts']:.0f}W")
        print(f"  Utilization:     {c['utilization_percent']:.1f}%")
        print(f"  Throttle:        {c['throttle_action']}")
        print(f"  Cooling limit:   {cc['constraint_severity']}")
        print(f"  Max safe power:  {cc['max_safe_power_watts']:.0f}W")
        if c["thermal_alerts"]:
            print(f"  Thermal alerts:  {len(c['thermal_alerts'])}")
            for a in c["thermal_alerts"]:
                print(f"    {a['gpu_id']}: {a['severity'].upper()} ({a['current_temp']:.1f}°C)")
        print("="*70)
        return 0

    def cmd_cooling_forecast(self, args):
        w = self.orch.predictive_constraint_warning()
        print(f"\n{'='*70}\nCOOLING FORECAST\n{'='*70}")
        if w:
            print(f"  ⚠️  {w['minutes_until_constraint']:.1f} min until constraint")
            print(f"  Action: {w['recommended_action']}")
        else:
            print("  ✓ No predictive warnings. System healthy.")
        print("="*70)
        return 0

    def cmd_emergency_shutdown(self, args):
        result = self.orch.emergency_shutdown_sequence()
        print(f"\n{'='*70}\nEMERGENCY SHUTDOWN\n{'='*70}")
        if result["initiated"]:
            print("  🚨 INITIATED")
            for a in result["actions"]:
                print(f"  → {a}")
        else:
            print(f"  NOT INITIATED: {result['reason']}")
        print("="*70)
        return 0

    def cmd_health_report(self, args):
        health = self.orch.health_report()
        print(f"\n{'='*70}\nHEALTH REPORT\n{'='*70}")
        print(json.dumps(health, indent=2, default=str))
        print("="*70)
        return 0


def main():
    parser = argparse.ArgumentParser(description="Electricity CLI - Finite Power Grid Management")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("grid")
    p.add_argument("--tier", default="standard")
    p.set_defaults(func=lambda a: ElectricityCLI().cmd_grid_status(a))

    p = sub.add_parser("thermal")
    p.add_argument("--gpu-id", dest="gpu_id", required=True)
    p.add_argument("--temp", type=float, required=True)
    p.add_argument("--tier", default="standard")
    p.set_defaults(func=lambda a: ElectricityCLI().cmd_thermal_update(a))

    p = sub.add_parser("constraint")
    p.add_argument("--tier", default="standard")
    p.set_defaults(func=lambda a: ElectricityCLI().cmd_constraint_check(a))

    p = sub.add_parser("cooling")
    p.set_defaults(func=lambda a: ElectricityCLI().cmd_cooling_forecast(a))

    p = sub.add_parser("emergency")
    p.set_defaults(func=lambda a: ElectricityCLI().cmd_emergency_shutdown(a))

    p = sub.add_parser("health")
    p.set_defaults(func=lambda a: ElectricityCLI().cmd_health_report(a))

    args = parser.parse_args()
    if hasattr(args, "func"):
        return args.func(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
