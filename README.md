# ⚡ xAI Colossus Energy — Power Grid Management

[![Tests](https://img.shields.io/badge/tests-6%20passing-brightgreen.svg)](https://github.com/GlacierEQ/xai-colossus-energy)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![Pro-Code](https://img.shields.io/badge/Pro--Code-7--gate%20audit-brightgreen.svg)](PRO_CODE_AUDIT.md)

> Autonomous power grid management for a **1.5GW AI supercomputer**.
> Grid balancing · Megapack FSM · PUE optimization · Demand forecasting.

---

## Architecture

```
┌─────────────────────────────────────────┐
│        ENERGY ORCHESTRATOR              │
│  tick-driven · auto-balance · forecast  │
└──────────┬──────────────────────────────┘
           │
    ┌──────┼──────┬──────┬──────┐
    ▼      ▼      ▼      ▼      ▼
  GRID   MEGAPACK  PUE  DEMAND  UTILITY
  BALANCER  FSM   OPTIMIZER FORECAST
```

## Quick Start

```python
from energy.grid_balancer import GridBalancer
import asyncio

balancer = GridBalancer()
zones = {f"Z{i}": {"gpu_utilization": 0.8} for i in range(4)}

result = asyncio.run(balancer.tick(zones, tick_num=1))
print(f"State: {result['state']}, Utilization: {result['utilization_pct']:.1f}%")
```

## Power Sources

| Source | Capacity | Efficiency | Role |
|--------|----------|------------|------|
| **Utility Grid** | 800 MW | 98% | Baseload |
| **Solar Array** | 200 MW | 22% | Daytime supplement |
| **Megapack Battery** | 300 MW | 92% | Peak shaving, backup |
| **Generator** | 200 MW | 35% | Emergency backup |

## Grid States

| State | Condition | Action |
|-------|-----------|--------|
| NOMINAL | Utilization < 75% | Normal operation |
| STRESSED | 75% ≤ Utilization < 90% | Warning, optimize load |
| CRITICAL | Utilization ≥ 90% | Activate backup generators |
| EMERGENCY | Grid failure | Load shedding |

## Double Helix

**Alpha (What)**: `energy/` — Grid balancer, Megapack FSM, PUE optimizer
**Omega (How)**: `orchestrator/` — Energy orchestrator, forecasting pipeline

See [`HELIX.md`](HELIX.md) for architecture details.

## Testing

```bash
python -m pytest tests/ -v
```

**6 tests** passing: state management, utilization calculation, headroom tracking, summary structure.

## Scale

| Metric | Value |
|--------|-------|
| Total capacity | 1.5 GW |
| Power sources | 4 |
| Grid states | 5 |
| Tick interval | 500ms |
| PUE target | < 1.1 |

---

> *"1.5GW balanced. Every watt accounted for."*
