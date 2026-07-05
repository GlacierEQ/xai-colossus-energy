"""src/energy/pue_tracker.py — PUE Tracker Module (Issue #7)

Gate requirement: PUE < 1.45 sustained over 24 hours.

The PUETracker records one reading per balance tick, maintains a rolling
24-hour window, and exposes `pue_24h_avg` and `is_gate_passing` for the
Phase 3→4 deployment gate check.

PUE = (IT load + cooling + PDU + lighting) / IT load

Default estimates (override with real sensor feeds when available):
  cooling_ratio : 0.35 of IT load  (≅ good air-cooled DC, Memphis climate)
  pdu_ratio     : 0.04 of IT load
  lighting_ratio: 0.005 of IT load

Alerts
------
  WARNING   : rolling PUE > 1.40 (amber — trending toward gate fail)
  CRITICAL  : rolling PUE > 1.45 for > 5 consecutive readings (gate fail)
"""

import logging
import time
import uuid
from collections import deque
from typing import Deque, Optional, Tuple

logger = logging.getLogger("PUETracker")

PUE_GATE_LIMIT        = 1.45   # Phase 3→4 gate threshold
PUE_WARN_THRESHOLD    = 1.40   # amber warning
PUE_ALERT_CYCLES      = 5      # consecutive over-limit readings before CRITICAL
WINDOW_SECONDS        = 86400  # 24 hours rolling window

DEFAULT_COOLING_RATIO  = 0.35
DEFAULT_PDU_RATIO      = 0.04
DEFAULT_LIGHTING_RATIO = 0.005


class PUETracker:
    """
    Rolling 24-hour PUE tracker for Colossus.

    Parameters
    ----------
    sb : optional
        Supabase client. Writes energy_telemetry rows when provided.
        If None, telemetry is only logged (CI safe).
    cooling_ratio, pdu_ratio, lighting_ratio : float
        Overhead fractions of IT load used when real sensor data is
        unavailable. Replace with live sensor feeds in production.
    """

    def __init__(
        self,
        sb=None,
        cooling_ratio: float = DEFAULT_COOLING_RATIO,
        pdu_ratio: float = DEFAULT_PDU_RATIO,
        lighting_ratio: float = DEFAULT_LIGHTING_RATIO,
    ):
        self._sb = sb
        self._cooling_ratio  = cooling_ratio
        self._pdu_ratio      = pdu_ratio
        self._lighting_ratio = lighting_ratio

        # Rolling window: deque of (timestamp, pue) tuples
        self._window: Deque[Tuple[float, float]] = deque()
        self._over_limit_count: int = 0
        self._critical_written: bool = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def record(
        self,
        it_load_kw: float,
        cooling_kw: Optional[float] = None,
        pdu_kw: Optional[float] = None,
        lighting_kw: Optional[float] = None,
        zone: str = "all",
    ) -> float:
        """Record one PUE reading and write to Supabase if available.

        Parameters
        ----------
        it_load_kw : float
            Total IT load in kW (servers + networking).
        cooling_kw, pdu_kw, lighting_kw : float, optional
            Actual overhead values from sensors. If None, estimates are
            derived from it_load_kw using the configured ratios.

        Returns
        -------
        float
            Instantaneous PUE for this reading.
        """
        if it_load_kw <= 0:
            return 1.0  # avoid div-by-zero; undefined PUE at zero load

        cooling  = cooling_kw  if cooling_kw  is not None else it_load_kw * self._cooling_ratio
        pdu      = pdu_kw      if pdu_kw      is not None else it_load_kw * self._pdu_ratio
        lighting = lighting_kw if lighting_kw is not None else it_load_kw * self._lighting_ratio
        total_kw = it_load_kw + cooling + pdu + lighting
        pue      = total_kw / it_load_kw

        ts = time.time()
        self._window.append((ts, pue))
        self._evict_old(ts)
        self._check_alerts(pue)
        self._write_telemetry(ts, pue, it_load_kw, cooling, pdu, lighting, zone)
        return pue

    @property
    def pue_24h_avg(self) -> Optional[float]:
        """Rolling 24-hour average PUE. None if no readings recorded yet."""
        if not self._window:
            return None
        return sum(p for _, p in self._window) / len(self._window)

    @property
    def is_gate_passing(self) -> bool:
        """True if rolling 24h average PUE is below the gate limit (1.45)."""
        avg = self.pue_24h_avg
        return avg is not None and avg < PUE_GATE_LIMIT

    @property
    def reading_count(self) -> int:
        """Number of readings in the current 24h window."""
        return len(self._window)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_old(self, now: float) -> None:
        """Remove readings older than WINDOW_SECONDS from the left of the deque."""
        cutoff = now - WINDOW_SECONDS
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()

    def _check_alerts(self, pue: float) -> None:
        avg = self.pue_24h_avg
        if avg is None:
            return
        if avg > PUE_WARN_THRESHOLD:
            logger.warning(
                "PUE WARNING: 24h avg %.4f > %.2f (amber threshold)",
                avg, PUE_WARN_THRESHOLD,
            )
        if avg > PUE_GATE_LIMIT:
            self._over_limit_count += 1
            if self._over_limit_count >= PUE_ALERT_CYCLES and not self._critical_written:
                self._critical_written = True
                logger.error(
                    "PUE GATE FAIL: 24h avg %.4f > %.2f for %d consecutive readings — "
                    "Phase 3→4 gate BLOCKED",
                    avg, PUE_GATE_LIMIT, self._over_limit_count,
                )
                self._write_pue_critical(avg)
        else:
            self._over_limit_count = 0
            self._critical_written = False

    def _write_telemetry(self, ts, pue, it_kw, cooling_kw, pdu_kw, lighting_kw, zone):
        if self._sb is None:
            return
        row = {
            "id":           str(uuid.uuid4()),
            "ts":           ts,
            "pue":          round(pue, 4),
            "it_load_kw":   round(it_kw, 1),
            "cooling_kw":   round(cooling_kw, 1),
            "pdu_kw":       round(pdu_kw, 1),
            "lighting_kw":  round(lighting_kw, 2),
            "total_kw":     round(it_kw + cooling_kw + pdu_kw + lighting_kw, 1),
            "pue_24h_avg":  round(self.pue_24h_avg, 4) if self.pue_24h_avg else None,
            "zone":         zone,
        }
        try:
            self._sb.table("energy_telemetry").insert(row).execute()
        except Exception as exc:
            logger.error("PUETracker energy_telemetry write failed: %s", exc)

    def _write_pue_critical(self, avg_pue: float) -> None:
        if self._sb is None:
            return
        row = {
            "id":         str(uuid.uuid4()),
            "event_type": "PUE_GATE_FAIL",
            "severity":   "CRITICAL",
            "payload": {
                "pue_24h_avg": round(avg_pue, 4),
                "gate_limit":  PUE_GATE_LIMIT,
                "readings_over": self._over_limit_count,
            },
            "ts":         time.time(),
        }
        try:
            self._sb.table("audit_events").insert(row).execute()
        except Exception as exc:
            logger.error("PUETracker audit_events write failed: %s", exc)
