# electricity/

**Migrated from [`GlacierEQ/electricity`](https://github.com/GlacierEQ/electricity) — that repo is now archived.**

This package owns all finite-bounded power grid physics for the Colossus cooling OS:
- First-principles thermal-power correlation (`electricity_apex_boot_core.py`)
- Constraint orchestration with predictive throttling (`electricity_thermal_orchestrator.py`)
- FastAPI real-time bridge to xai-colossus-cooling (`electricity_xai_bridge.py`)
- Plotly Dash live dashboard (`electricity_xai_dash_dashboard.py`)
- CLI for grid/thermal/constraint/emergency commands (`electricity_cli.py`)

## Install dependencies
```bash
pip install fastapi uvicorn pydantic dash plotly pandas numpy
```

## Quick start
```python
from electricity import APEXPowerGrid, GridTier, ElectricityThermalOrchestrator

grid = APEXPowerGrid(GridTier.STANDARD)   # 128 GPUs, 150 kW
grid.register_gpu("gpu-000")
grid.update_gpu_temp("gpu-000", 65.0)
print(grid.grid_status())
```

## CLI
```bash
python -m electricity.electricity_cli grid --tier standard
python -m electricity.electricity_cli thermal --gpu-id gpu-000 --temp 72.5
python -m electricity.electricity_cli constraint
python -m electricity.electricity_cli cooling
```

## Bridge (FastAPI)
```bash
python electricity/electricity_xai_bridge.py
# API: http://localhost:8000/docs
```

## Dashboard (Dash)
```bash
python electricity/electricity_xai_dash_dashboard.py
# Dashboard: http://localhost:8050
```

## Grid tiers
| Tier | GPUs | Max kW |
|------|------|--------|
| MICRO | 8 | 10 |
| MINI | 32 | 40 |
| STANDARD | 128 | 150 |
| COLOSSAL | 512 | 600 |
| MEGA | 8000 | 5,000 |
