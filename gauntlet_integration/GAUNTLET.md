# Gauntlet Integration Contract

This directory defines how `xai-colossus-energy` talks to the Gauntlet simulation / planning layer.

## Objectives

- Expose real-time and forecasted power demand per zone.
- Accept optimization plans (e.g. which Megapack to charge/discharge).
- Close the loop between physical energy state and simulation outputs.

## Interfaces

### Outbound (Energy → Gauntlet)

- Endpoint: `POST /v1/energy/state`
- Payload: aggregated `power_state` snapshot:
  - per-zone KW
  - Megapack SoC
  - grid price
  - forecast window (next 24–72 hours)

### Inbound (Gauntlet → Energy)

- Endpoint: `POST /v1/energy/plan`
- Payload: `dispatch_plan`:
  - per-hour Megapack charge/discharge schedule
  - max grid draw caps per zone
  - flex load shifts (non-critical cooling / compute)

All payloads should comply with the JSON Schemas defined in `schemas/` (see `power_state.json`).
