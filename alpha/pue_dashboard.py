# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
"""
Real-Time PUE Dashboard with Historical Tracking
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Provides PUE visualization, chart data export, and configurable alert thresholds.
Designed for APEX orchestrator integration with JSONL persistence.
"""

import json
import time
import os
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Deque
from collections import deque
from pathlib import Path

logger = logging.getLogger("PUEDashboard")

DEFAULT_LOG_DIR = "audit_logs"
DEFAULT_HISTORY_SIZE = 1440  # 24h at 1-minute resolution
ALERT_COOLDOWN_S = 300


@dataclass(frozen=True)
class PUEAlertThresholds:
    warning: float = 1.30
    critical: float = 1.45
    emergency: float = 1.60
    sustained_duration_s: int = 300


@dataclass
class PUEDataPoint:
    timestamp: float
    pue: float
    total_facility_power_mw: float
    it_load_mw: float
    cooling_load_mw: float
    other_load_mw: float
    outside_temp_c: Optional[float] = None
    zone: str = "facility"

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "iso_time": datetime.fromtimestamp(self.timestamp).isoformat(),
            "pue": round(self.pue, 4),
            "total_facility_power_mw": round(self.total_facility_power_mw, 2),
            "it_load_mw": round(self.it_load_mw, 2),
            "cooling_load_mw": round(self.cooling_load_mw, 2),
            "other_load_mw": round(self.other_load_mw, 2),
            "outside_temp_c": self.outside_temp_c,
            "zone": self.zone,
        }


@dataclass
class PUEAlertState:
    current_level: str = "normal"
    sustained_high_start: Optional[float] = None
    last_alert_time: float = 0.0
    alert_count: int = 0
    peak_pue_24h: float = 0.0
    avg_pue_1h: float = 0.0


class PUEDashboard:
    def __init__(
        self,
        thresholds: Optional[PUEAlertThresholds] = None,
        log_dir: str = DEFAULT_LOG_DIR,
        history_size: int = DEFAULT_HISTORY_SIZE,
    ):
        self.thresholds = thresholds or PUEAlertThresholds()
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.history: Deque[PUEDataPoint] = deque(maxlen=history_size)
        self.alert_state = PUEAlertState()
        self._log_file_handle = None
        self._open_log_file()
        logger.info(
            f"PUEDashboard initialized: thresholds=[warning={self.thresholds.warning}, "
            f"critical={self.thresholds.critical}, emergency={self.thresholds.emergency}]"
        )

    def _open_log_file(self) -> None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_path = self.log_dir / f"pue_{date_str}.jsonl"
        self._log_file_handle = open(log_path, "a", encoding="utf-8")
        self._current_log_date = date_str

    def _rotate_log_if_needed(self) -> None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        if date_str != self._current_log_date:
            if self._log_file_handle:
                self._log_file_handle.close()
            self._open_log_file()

    def ingest(
        self,
        total_facility_power_mw: float,
        it_load_mw: float,
        outside_temp_c: Optional[float] = None,
        zone: str = "facility",
    ) -> PUEDataPoint:
        if it_load_mw <= 0:
            logger.error(f"Invalid IT load: {it_load_mw} MW — using zero PUE")
            pue = 0.0
        else:
            pue = total_facility_power_mw / it_load_mw

        cooling_load = total_facility_power_mw - it_load_mw
        other_load = max(0.0, cooling_load - cooling_load)

        dp = PUEDataPoint(
            timestamp=time.time(),
            pue=pue,
            total_facility_power_mw=total_facility_power_mw,
            it_load_mw=it_load_mw,
            cooling_load_mw=cooling_load,
            other_load_mw=other_load,
            outside_temp_c=outside_temp_c,
            zone=zone,
        )
        self.history.append(dp)
        self._update_alert_state(dp)
        self._persist(dp)
        return dp

    def _update_alert_state(self, dp: PUEDataPoint) -> None:
        now = time.time()
        pue = dp.pue

        if pue > self.alert_state.peak_pue_24h:
            self.alert_state.peak_pue_24h = pue

        recent = [d for d in self.history if now - d.timestamp <= 3600]
        if recent:
            self.alert_state.avg_pue_1h = sum(d.pue for d in recent) / len(recent)

        if pue >= self.thresholds.emergency:
            self._raise_alert("emergency", pue, now)
        elif pue >= self.thresholds.critical:
            if self.alert_state.sustained_high_start is None:
                self.alert_state.sustained_high_start = now
            elif now - self.alert_state.sustained_high_start >= self.thresholds.sustained_duration_s:
                self._raise_alert("critical", pue, now)
        elif pue >= self.thresholds.warning:
            if self.alert_state.sustained_high_start is None:
                self.alert_state.sustained_high_start = now
            elif now - self.alert_state.sustained_high_start >= self.thresholds.sustained_duration_s:
                self._raise_alert("warning", pue, now)
        else:
            self.alert_state.sustained_high_start = None
            self.alert_state.current_level = "normal"

    def _raise_alert(self, level: str, pue: float, now: float) -> None:
        if now - self.alert_state.last_alert_time < ALERT_COOLDOWN_S:
            return
        self.alert_state.current_level = level
        self.alert_state.last_alert_time = now
        self.alert_state.alert_count += 1
        msg = f"PUE_ALERT [{level.upper()}]: pue={pue:.3f}, threshold={getattr(self.thresholds, level)}"
        logger.warning(msg)

    def _persist(self, dp: PUEDataPoint) -> None:
        self._rotate_log_if_needed()
        entry = dp.to_dict()
        entry["alert_level"] = self.alert_state.current_level
        self._log_file_handle.write(json.dumps(entry) + "\n")
        self._log_file_handle.flush()

    def get_chart_data(self, duration_s: int = 3600) -> Dict:
        now = time.time()
        cutoff = now - duration_s
        points = [d for d in self.history if d.timestamp >= cutoff]
        if not points:
            return {"timestamps": [], "pue": [], "it_load": [], "cooling_load": [], "summary": {}}
        return {
            "timestamps": [datetime.fromtimestamp(p.timestamp).isoformat() for p in points],
            "pue": [round(p.pue, 4) for p in points],
            "it_load": [round(p.it_load_mw, 2) for p in points],
            "cooling_load": [round(p.cooling_load_mw, 2) for p in points],
            "summary": self.get_summary(),
        }

    def get_summary(self) -> Dict:
        if not self.history:
            return {"avg_pue": 0, "min_pue": 0, "max_pue": 0, "sample_count": 0}
        pues = [d.pue for d in self.history]
        return {
            "avg_pue": round(sum(pues) / len(pues), 4),
            "min_pue": round(min(pues), 4),
            "max_pue": round(max(pues), 4),
            "peak_24h": round(self.alert_state.peak_pue_24h, 4),
            "avg_1h": round(self.alert_state.avg_pue_1h, 4),
            "sample_count": len(pues),
            "alert_level": self.alert_state.current_level,
            "total_alerts": self.alert_state.alert_count,
        }

    def export_json(self, filepath: str, duration_s: Optional[int] = None) -> int:
        now = time.time()
        if duration_s:
            cutoff = now - duration_s
            points = [d for d in self.history if d.timestamp >= cutoff]
        else:
            points = list(self.history)
        data = [d.to_dict() for d in points]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({"export_time": datetime.now().isoformat(), "data_points": data}, f, indent=2)
        logger.info(f"Exported {len(data)} data points to {filepath}")
        return len(data)

    def close(self) -> None:
        if self._log_file_handle:
            self._log_file_handle.close()


if __name__ == "__main__":
    dashboard = PUEDashboard()
    for i in range(5):
        total = 200.0 + (i * 10)
        it_load = 150.0
        dp = dashboard.ingest(total, it_load)
        print(f"[{i}] PUE={dp.pue:.3f}, total={total}MW, it={it_load}MW")
    print(f"\nSummary: {dashboard.get_summary()}")
    print(f"Chart data (last 60s): {dashboard.get_chart_data(60)}")
    dashboard.close()
