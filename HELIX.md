# 🔱 Double Helix: xAI Colossus Energy

> Alpha (What) + Omega (How) = Autonomous power grid management for 1.5GW AI supercomputer.

```
BINDING: DOUBLE_HELIX:COLOSSUS_ENERGY v1.0
PAIR:    Alpha (grid physics) ←→ Omega (forecasting + CI)
MANTRA:  Two strands. One autonomous energy DNA.
```

## 🧬 Alpha Strand (What — Domain Logic)

The physics-first energy management system.

### Core Files
| File | Purpose |
|------|---------|
| `energy/grid_balancer.py` | 1.5GW grid load balancing |
| `energy/megapack_state_machine.py` | 8-state Megapack FSM |
| `energy/pue_optimizer.py` | Power Usage Effectiveness optimization |
| `energy/demand_forecaster.py` | ML-based demand forecasting |
| `physics/constants.py` | Shared physics (Maxwell, Hamilton-Crosser) |

### Alpha Contract
```python
class EnergySubsystem:
    """Every energy module MUST expose tick() + summary()"""
    async def tick(self, zones: Dict, tick_num: int) -> Dict[str, Any]:
        return {"anomalies": [...], "actions": [...]}
    
    def summary(self) -> Dict[str, Any]:
        return {"status": "...", "metrics": {...}}
```

## 🌀 Omega Strand (How — Orchestration)

The operational intelligence layer.

### Core Files
| File | Purpose |
|------|---------|
| `orchestrator/energy_orchestrator.py` | Central energy brain |
| `api/energy_gateway.py` | REST gateway for energy endpoints |
| `forecasting/ml_pipeline.py` | Demand prediction pipeline |
| `memory/energy_memory.py` | Historical energy data persistence |
| `cli/energy_cli.py` | Energy management CLI |

### Omega Contract
```python
class EnergyOrchestrator:
    """Omega orchestrates Alpha energy subsystems"""
    async def run(self, duration_ticks: int = 100):
        for tick in range(duration_ticks):
            forecast = await self.forecaster.predict(tick)
            balance = await self.grid_balancer.balance(forecast)
            self.megapack.optimize(balance)
            await asyncio.sleep(0.5)
```

## 🔄 Helix Interlock

Alpha and Omega communicate through:
1. **Subsystem Interface** — `tick() → {anomalies, actions}`
2. **Power State Bus** — Real-time power state propagation
3. **Forecast Feedback** — ML predictions feed back into grid balancing
4. **Megapack State Machine** — 8-state FSM with graceful transitions

## 📊 Pro-Code Binding

| Gate | Status |
|------|--------|
| Naming (snake_case, prefixes) | ✅ |
| Architecture (subsystem contract) | ✅ |
| Failure handling (state machine) | ✅ |
| Maintainability (modular design) | ✅ |
| Authenticity (physics-first) | ✅ |
| Observability (power metrics) | ✅ |
| Documentation (AGENTS.md) | ✅ |

## 🎯 Job Application Angle

This repo demonstrates:
- **Power systems knowledge** — Grid balancing, PUE optimization, Megapack FSM
- **ML engineering** — Demand forecasting, predictive dispatch
- **Scale awareness** — 1.5GW, 200k GPUs, utility-scale power
- **Reliability engineering** — State machines, graceful degradation
- **Operational excellence** — Real-time monitoring, automated response
