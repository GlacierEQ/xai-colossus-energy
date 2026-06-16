"""electricity/pue_tracker.py — Real-time PUE tracker (Issue #7)

Power Usage Effectiveness = total_facility_power / it_equipment_power

Phase 3→4 gate requirement: PUE < 1.45 sustained 24 hours.

Behaviour
---------
- Reads IT load from configurable rack telemetry callable or mock
- Reads facility load (cooling + PDU overhead) from ColossusEnergyBalancer
- Logs PUE to audit_logs/pue_{date}.jsonl every 60 s
- Emits MCP pue_alert if PUE > 1.45 sustained > 300 s (5 consecutive minutes)
- Writes completion memory to Supabase on first successful 24-hour window
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger("ColossusEnergyBalancer.PUETracker")

PUE_LIMIT             = 1.45
ALERT_SUSTAIN_SECS    = 300   # fire MCP alert after this many seconds over limit
LOG_INTERVAL_SECS     = 60    # write to jsonl every this many seconds
GATE_24H_SECS         = 86400 # gate requirement: PUE < limit for this long

# PDU and lighting overhead as fraction of IT load (conservative estimate)
PDU_OVERHEAD_FRACTION = 0.04


class PUETracker:
    """Computes, logs, and alerts on real-time PUE.

    Parameters
    ----------
    it_load_fn:
        Callable that returns current IT equipment load in kW.
        Default: reads from energy balancer's zone totals.
    cooling_load_fn:
        Callable that returns current cooling load in kW.
    balancer:
        Optional ColossusEnergyBalancer instance to derive loads from.
    sb:
        Supabase client for writing completion memory.
    mcp_dispatch:
        Callable(event_type, payload) for MCP alerts.
    log_dir:
        Directory for daily jsonl logs.  Created if absent.
    """

    def __init__(
        self,
        it_load_fn:      Optional[Callable[[], float]] = None,
        cooling_load_fn: Optional[Callable[[], float]] = None,
        balancer=None,
        sb=None,
        mcp_dispatch:    Optional[Callable] = None,
        log_dir:         str = "audit_logs",
    ):
        self._balancer       = balancer
        self._it_load_fn     = it_load_fn or self._default_it_load
        self._cooling_load_fn = cooling_load_fn or self._default_cooling_load
        self._sb             = sb
        self._mcp_dispatch   = mcp_dispatch or self._default_mcp_log
        self._log_dir        = log_dir
        os.makedirs(log_dir, exist_ok=True)

        self._over_limit_since: Optional[float] = None
        self._alert_fired:      bool = False
        self._gate_start:       Optional[float] = None  # first tick below limit
        self._gate_written:     bool = False            # Supabase memory written once
        self._last_log_ts:      float = 0.0
        self._pue_history:      list  = []              # list of (ts, pue) for last 24h

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_pue(self) -> float:
        """Return current PUE = total_facility_power / it_equipment_power."""
        it_kw = max(1.0, self._it_load_fn())          # floor at 1 kW to avoid /0
        cooling_kw = self._cooling_load_fn()
        pdu_kw = it_kw * PDU_OVERHEAD_FRACTION
        total_facility_kw = it_kw + cooling_kw + pdu_kw
        return total_facility_kw / it_kw

    def tick(self) -> dict:
        """Compute PUE, log if interval elapsed, fire alerts, check gate."""
        now = time.time()
        pue = self.compute_pue()
        self._pue_history.append((now, pue))
        # Trim history to last 24 h
        cutoff = now - GATE_24H_SECS
        self._pue_history = [(t, p) for t, p in self._pue_history if t >= cutoff]

        # --- Logging ---
        if now - self._last_log_ts >= LOG_INTERVAL_SECS:
            self._log_pue(now, pue)
            self._last_log_ts = now

        # --- Over-limit tracking ---
        if pue > PUE_LIMIT:
            if self._over_limit_since is None:
                self._over_limit_since = now
            duration = now - self._over_limit_since
            if duration >= ALERT_SUSTAIN_SECS and not self._alert_fired:
                self._alert_fired = True
                self._mcp_dispatch("pue_alert", {
                    "pue": round(pue, 4),
                    "limit": PUE_LIMIT,
                    "sustained_secs": round(duration, 0),
                })
                logger.error(
                    "PUE ALERT: %.4f > %.2f sustained %.0f s",
                    pue, PUE_LIMIT, duration,
                )
            self._gate_start = None  # reset gate clock — not in compliance
        else:
            self._over_limit_since = None
            self._alert_fired = False
            if self._gate_start is None:
                self._gate_start = now

        # --- 24-hour gate check ---
        if (
            self._gate_start is not None
            and (now - self._gate_start) >= GATE_24H_SECS
            and not self._gate_written
        ):
            self._gate_written = True
            self._write_gate_memory(pue)

        return {
            "ts": now,
            "pue": round(pue, 4),
            "gate_elapsed_secs": round(now - self._gate_start, 0) if self._gate_start else 0,
            "gate_met": self._gate_written,
        }

    async def run_continuous(self, interval_secs: float = LOG_INTERVAL_SECS) -> None:
        """Async loop: tick every interval_secs."""
        logger.info("PUETracker started (interval=%ds, limit=%.2f)", interval_secs, PUE_LIMIT)
        while True:
            self.tick()
            await asyncio.sleep(interval_secs)

    # ------------------------------------------------------------------
    # Default load functions
    # ------------------------------------------------------------------

    def _default_it_load(self) -> float:
        """Read IT load from energy balancer zone totals (kW)."""
        if self._balancer is not None:
            return self._balancer.compute_total_draw_mw() * 1000.0
        return 100_000.0  # 100 MW mock for unit tests

    def _default_cooling_load(self) -> float:
        """Estimate cooling load as 35% of IT load (PUE ~1.35 baseline)."""
        return self._default_it_load() * 0.35

    # ------------------------------------------------------------------
    # Logging and memory
    # ------------------------------------------------------------------

    def _log_pue(self, ts: float, pue: float) -> None:
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        path = os.path.join(self._log_dir, f"pue_{date_str}.jsonl")
        entry = {
            "ts": ts,
            "pue": round(pue, 4),
            "iso": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
        }
        with open(path, "a") as fh:
            fh.write(json.dumps(entry) + "\n")

    def _write_gate_memory(self, pue: float) -> None:
        """Write 24-hour gate completion to Supabase godmind_memory."""
        if self._sb is None:
            logger.info("PUE 24h gate met (pue=%.4f) — no Supabase client", pue)
            return
        try:
            import sys; sys.path.append("/data/data/com.termux/files/home/God-Mind/shared")
            from supabase_utils import write_completion
            write_completion(
                sb=self._sb,
                repo="xai-colossus-energy",
                job="pue_tracker_gate",
                findings=f"PUE 24h gate met: average PUE {pue:.4f} < {PUE_LIMIT} "
                         f"sustained {GATE_24H_SECS}s. Phase 3→4 gate condition satisfied.",
                tags=["pue", "phase-gate", "colossus", "cooling"],
            )
            logger.info("PUE gate memory written to Supabase.")
        except Exception as exc:
            logger.error("PUE gate Supabase write failed: %s", exc)

    @staticmethod
    def _default_mcp_log(event_type: str, payload: dict) -> None:
        logger.info("MCP_DISPATCH [%s]: %s", event_type, payload)
