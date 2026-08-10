"""Supabase telemetry for ``ColossusEnergyBalancer``.

Canonical GlacierEQ sinks:
  1. Startup/runtime telemetry -> ``apex_loop_health``
  2. PUE cycle telemetry       -> ``apex_loop_health`` metadata
  3. Critical PUE receipts     -> ``apex_ops_log``

The retired ``connector_jobs`` queue and nonexistent ``energy_telemetry`` /
``audit_events`` tables are intentionally not used.
"""

import json
import logging

logger = logging.getLogger("ColossusEnergyBalancer.Supabase")

PUE_ALERT_THRESHOLD = 1.45
PUE_ALERT_CYCLES = 5


class SupabaseTelemetryMixin:
    """Add GlacierEQ observability writes to ``ColossusEnergyBalancer``."""

    def __init__(self, *args, sb=None, **kwargs):
        super().__init__(*args, **kwargs)
        if sb is not None:
            self._sb = sb
        self._pue_over_cycles = 0
        self._pue_critical_written = False

    def start_with_heartbeat(self) -> None:
        """Write startup health and then begin continuous operation."""
        self._write_heartbeat()
        self.run_continuous()

    def _write_heartbeat(self) -> None:
        if self._sb is None:
            logger.info("Heartbeat: no Supabase client — skipping")
            return

        row = {
            "component": "xai_energy_balancer",
            "layer": "energy_runtime",
            "status": "HEALTHY",
            "operator": "xai_energy_balancer",
            "target_service": "xai-colossus-energy",
            "metadata": {
                "event": "startup",
                "grid_capacity_mva": self.grid_capacity_mva,
                "megapack_soc_pct": self.megapack.soc_pct,
                "zones": list(self.zones.keys()),
                "contract": "glaciereq-apex-loop-health-v1",
            },
        }
        try:
            self._sb.table("apex_loop_health").insert(row).execute()
            logger.info("Heartbeat written to apex_loop_health")
        except Exception as exc:
            logger.error("Heartbeat Supabase write failed: %s", exc)

    def write_cycle_telemetry(self, zone: str = "all") -> None:
        """Write one PUE observation to the canonical loop-health surface."""
        it_kw = self.compute_total_draw_mw() * 1000.0
        cooling_kw = it_kw * 0.35
        pdu_kw = it_kw * 0.04
        total_kw = it_kw + cooling_kw + pdu_kw
        pue = total_kw / max(1.0, it_kw)

        if self._sb is not None:
            row = {
                "component": "xai_energy_balancer",
                "layer": "energy_telemetry",
                "status": "DEGRADED" if pue > PUE_ALERT_THRESHOLD else "HEALTHY",
                "operator": "xai_energy_balancer",
                "target_service": "xai-colossus-energy",
                "metadata": {
                    "pue": round(pue, 4),
                    "total_kw": round(total_kw, 1),
                    "it_load_kw": round(it_kw, 1),
                    "cooling_kw": round(cooling_kw, 1),
                    "pdu_kw": round(pdu_kw, 1),
                    "zone": zone,
                    "threshold": PUE_ALERT_THRESHOLD,
                    "contract": "glaciereq-apex-loop-health-v1",
                },
            }
            try:
                self._sb.table("apex_loop_health").insert(row).execute()
            except Exception as exc:
                logger.error("apex_loop_health telemetry write failed: %s", exc)

        if pue > PUE_ALERT_THRESHOLD:
            self._pue_over_cycles += 1
            if self._pue_over_cycles >= PUE_ALERT_CYCLES and not self._pue_critical_written:
                self._write_pue_critical(pue)
        else:
            self._pue_over_cycles = 0
            self._pue_critical_written = False

    def _write_pue_critical(self, pue: float) -> None:
        """Write one idempotent critical PUE receipt for the active streak."""
        if self._pue_critical_written:
            return

        if self._sb is None:
            logger.error(
                "PUE CRITICAL: %.4f > %.2f for %d cycles (no Supabase)",
                pue,
                PUE_ALERT_THRESHOLD,
                self._pue_over_cycles,
            )
            self._pue_critical_written = True
            return

        row = {
            "action": "xai_energy_balancer_pue_critical",
            "status": "critical",
            "details": json.dumps(
                {
                    "repo": "xai-colossus-energy",
                    "pue": round(pue, 4),
                    "threshold": PUE_ALERT_THRESHOLD,
                    "cycles_over": self._pue_over_cycles,
                    "contract": "glaciereq-apex-ops-log-v1",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        try:
            self._sb.table("apex_ops_log").insert(row).execute()
            self._pue_critical_written = True
            logger.error(
                "PUE CRITICAL written to apex_ops_log: pue=%.4f (%d cycles)",
                pue,
                self._pue_over_cycles,
            )
        except Exception as exc:
            logger.error("apex_ops_log CRITICAL write failed: %s", exc)
