# Megapack Buffer Spec

Model of the Tesla Megapack-based energy buffer for Colossus 2.

## Core Concepts

- Each Megapack has:
  - `name` / `id`
  - `capacity_mwh`
  - `max_charge_mw`
  - `max_discharge_mw`
  - `state_of_charge_pct`
  - `round_trip_efficiency_pct`

- The buffer layer:
  - absorbs grid price spikes by discharging during high-cost periods;
  - charges during low-cost periods or excess renewable production;
  - provides ride-through capacity for transient grid events.

## Integration Points

- `xai_energy_balancer.py` should:
  - compute an optimal dispatch schedule given:
    - grid price curve,
    - expected load,
    - SoC bounds.
  - emit Megapack state events using the audit schema.

## Done Definition

- [ ] At least one Megapack modeled with real-world parameters.
- [ ] Dispatch simulation for 24h horizon implemented.
- [ ] Hooks into Gauntlet planning loop operational.
