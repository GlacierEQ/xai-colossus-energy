"""xai_energy_balancer_supabase.py — Supabase telemetry layer for ColossusEnergyBalancer (Issue #1)

Patches ColossusEnergyBalancer to:
  1. Write a startup heartbeat to connector_jobs
  2. Write PUE telemetry to energy_telemetry on every balance cycle
  3. Write CRITICAL event to audit_events if PUE > 1.45 for > 5 consecutive cycles

Usage
-----
    from xai_energy_balancer import ColossusEnergyBalancer
    from xai_energy_balancer_supabase import SupabaseTelemetryMixin

    class InstrumentedBalancer(SupabaseTelemetryMixin, ColossusEnergyBalancer):
        pass

    balancer = InstrumentedBalancer(sb=supabase_client)
    balancer.start_with_heartbeat()
"""

import logging
import time
import uuid
from typing import Optional

logger = logging.getLogger("ColossusEnergyBalancer.Supabase")

PUE_ALERT_THRESHOLD  = 1.45
PUE_ALERT_CYCLES     = 5    # consecutive over-limit cycles before CRITICAL event


class SupabaseTelemetryMixin:
    """Mixin that adds Supabase telemetry to ColossusEnergyBalancer.

    The host class must implement:
      - compute_total_draw_mw() -> float
      - zones: Dict[str, ZoneController]  (used for cooling load estimate)

    Extra __init__ kwarg: sb (Supabase client).
    """

    def __init__(self, *args, sb=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._sb = sb
        self._pue_over_cycles = 0
        self._pue_critical_written = False

    # ------------------------------------------------------------------
    # Startup heartbeat
    # ------------------------------------------------------------------

    def start_with_heartbeat(self) -> None:
        """Write startup heartbeat then begin continuous operation."""
        self._write_heartbeat()
        self.run_continuous()  # from ColossusEnergyBalancer

    def _write_heartbeat(self) -> None:
        if self._sb is None:
            logger.info("Heartbeat: no Supabase client — skipping")
            return
        row = {
            "id": str(uuid.uuid4()),
            "connector": "xai_energy_balancer",
            "repo": "xai-colossus-energy",
            "status": "STARTED",
            "ts": time.time(),
            "metadata": {
                "grid_capacity_mva": self.grid_capacity_mva,
                "megapack_capacity_mwh": self.megapack.soc_pct,  # current SoC at boot
                "zones": list(self.zones.keys()),
            },
        }
        try:
            self._sb.table("connector_jobs").insert(row).execute()
            logger.info("Heartbeat written to connector_jobs")
        except Exception as exc:
            logger.error("Heartbeat Supabase write failed: %s", exc)

    # ------------------------------------------------------------------
    # Per-cycle telemetry — call this inside _control_loop
    # ------------------------------------------------------------------

    def write_cycle_telemetry(self, zone: str = "all") -> None:
        """Write one PUE telemetry row.  Call once per balance cycle."""
        it_kw  = self.compute_total_draw_mw() * 1000.0
        # Cooling estimate: 35% of IT load (conservative until PUETracker is running)
        cooling_kw = it_kw * 0.35
        pdu_kw     = it_kw * 0.04
        total_kw   = it_kw + cooling_kw + pdu_kw
        pue        = total_kw / max(1.0, it_kw)

        if self._sb is not None:
            row = {
                "id": str(uuid.uuid4()),
                "ts": time.time(),
                "pue": round(pue, 4),
                "total_kw": round(total_kw, 1),
                "it_load_kw": round(it_kw, 1),
                "cooling_kw": round(cooling_kw, 1),
                "zone": zone,
            }
            try:
                self._sb.table("energy_telemetry").insert(row).execute()
            except Exception as exc:
                logger.error("energy_telemetry Supabase write failed: %s", exc)

        # --- PUE over-limit tracking ---
        if pue > PUE_ALERT_THRESHOLD:
            self._pue_over_cycles += 1
            if self._pue_over_cycles >= PUE_ALERT_CYCLES and not self._pue_critical_written:
                self._pue_critical_written = True
                self._write_pue_critical(pue)
        else:
            self._pue_over_cycles = 0
            self._pue_critical_written = False

    def _write_pue_critical(self, pue: float) -> None:
        """Write CRITICAL event to audit_events (PUE > 1.45 for > 5 cycles).

        Idempotent: once a CRITICAL row is written for the current over-limit
        streak, further calls are no-ops until PUE returns under threshold
        (which clears ``_pue_critical_written`` in the tick path).
        """
        if self._pue_critical_written:
            return
        if self._sb is None:
            logger.error("PUE CRITICAL: %.4f > %.2f for >%d cycles (no Supabase)",
                         pue, PUE_ALERT_THRESHOLD, PUE_ALERT_CYCLES)
            self._pue_critical_written = True
            return
        row = {
            "id": str(uuid.uuid4()),
            "event_type": "PUE_CRITICAL",
            "severity": "CRITICAL",
            "payload": {
                "pue": round(pue, 4),
                "threshold": PUE_ALERT_THRESHOLD,
                "cycles_over": self._pue_over_cycles,
            },
            "ts": time.time(),
        }
        try:
            self._sb.table("audit_events").insert(row).execute()
            self._pue_critical_written = True
            logger.error(
                "PUE CRITICAL written to audit_events: pue=%.4f (%d cycles)",
                pue, self._pue_over_cycles,
            )
        except Exception as exc:
            logger.error("audit_events CRITICAL write failed: %s", exc)
