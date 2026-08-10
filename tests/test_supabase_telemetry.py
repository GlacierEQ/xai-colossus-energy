"""Acceptance tests for the canonical GlacierEQ telemetry contract.

Verify that:
  1. Startup heartbeat is written to apex_loop_health.
  2. PUE observations are written to apex_loop_health metadata.
  3. Threshold crossing writes one CRITICAL receipt to apex_ops_log.
  4. The critical receipt remains idempotent for one over-limit streak.
"""

from unittest.mock import MagicMock, patch

from xai_energy_balancer import ColossusEnergyBalancer
from xai_energy_balancer_supabase import (
    PUE_ALERT_CYCLES,
    SupabaseTelemetryMixin,
)


class InstrumentedBalancer(SupabaseTelemetryMixin, ColossusEnergyBalancer):
    pass


def _make_balancer(sb):
    return InstrumentedBalancer(sb=sb)


def _mock_sb():
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value = MagicMock()
    return sb


def _tables_written(sb):
    return [c.args[0] for c in sb.table.call_args_list]


def test_heartbeat_writes_to_apex_loop_health():
    sb = _mock_sb()
    b = _make_balancer(sb)
    b._write_heartbeat()
    assert "apex_loop_health" in _tables_written(sb)


def test_cycle_telemetry_writes_to_apex_loop_health():
    sb = _mock_sb()
    b = _make_balancer(sb)
    b.write_cycle_telemetry(zone="A")
    assert "apex_loop_health" in _tables_written(sb)


def test_pue_telemetry_row_has_canonical_metadata():
    written_rows = []

    class CapturingSB:
        def table(self, name):
            self._name = name
            return self

        def insert(self, row):
            if self._name == "apex_loop_health" and row.get("layer") == "energy_telemetry":
                written_rows.append(row)
            return self

        def execute(self):
            return MagicMock()

    b = InstrumentedBalancer(sb=CapturingSB())
    b.write_cycle_telemetry(zone="B")

    assert len(written_rows) == 1
    row = written_rows[0]
    assert row["component"] == "xai_energy_balancer"
    assert row["layer"] == "energy_telemetry"
    assert row["status"] in {"HEALTHY", "DEGRADED"}
    for field in ["pue", "total_kw", "it_load_kw", "cooling_kw", "pdu_kw", "zone", "threshold", "contract"]:
        assert field in row["metadata"], f"Missing metadata field: {field}"


def test_threshold_crossing_writes_one_critical_ops_receipt():
    sb = _mock_sb()
    b = _make_balancer(sb)
    b._pue_over_cycles = PUE_ALERT_CYCLES - 1

    # Normal model PUE is ~1.39. Lower the threshold so one real cycle crosses it.
    with patch("xai_energy_balancer_supabase.PUE_ALERT_THRESHOLD", 1.30):
        b.write_cycle_telemetry(zone="critical-test")

    assert "apex_ops_log" in _tables_written(sb)
    assert b._pue_critical_written is True


def test_pue_critical_not_fired_twice():
    sb = _mock_sb()
    b = _make_balancer(sb)
    b._pue_over_cycles = PUE_ALERT_CYCLES

    b._write_pue_critical(1.51)
    first_count = _tables_written(sb).count("apex_ops_log")
    b._write_pue_critical(1.51)
    second_count = _tables_written(sb).count("apex_ops_log")

    assert first_count == 1
    assert second_count == 1
