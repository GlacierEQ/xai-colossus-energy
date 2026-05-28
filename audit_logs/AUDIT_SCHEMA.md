# Energy Audit Log Schema

Standard schema for recording power and energy events in Colossus 2.

## Event Types

- `power_draw_snapshot` — periodic KW snapshot per rack/zone.
- `megapack_state` — charge/discharge state of Megapack buffer.
- `grid_event` — utility events: brownouts, outages, price spikes.
- `generator_event` — generator start/stop, fuel levels.

## Canonical Fields

- `event_id` (uuid)
- `timestamp` (ISO 8601)
- `source` (e.g. `ZONE-A`, `RACK-A01`, `MEGAPACK-01`)
- `event_type` (one of above)
- `value_kw` (for power_draw_snapshot, megapack_state)
- `state_of_charge_pct` (for Megapack)
- `grid_price_usd_per_mwh` (for grid_event)
- `metadata` (free-form JSON)

All audit logs should be emitted as NDJSON lines and written to:
`audit_logs/colossus_energy_events.ndjson`.
