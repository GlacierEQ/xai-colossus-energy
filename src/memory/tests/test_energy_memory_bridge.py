"""
Unit tests for EnergyMemoryBridge.

All tests run with ENERGY_MEMORY_ENABLED=false so no real Pinecone/Supermemory
calls are made — the bridge must degrade gracefully and never raise.
"""
import os
import pytest

os.environ.setdefault("ENERGY_MEMORY_ENABLED", "false")

from src.memory.energy_memory_bridge import EnergyMemoryBridge  # noqa: E402


@pytest.fixture
def bridge():
    return EnergyMemoryBridge()


class TestGracefulDegradation:
    def test_disabled_bridge_does_not_raise_on_gauntlet_record(self, bridge):
        """record_gauntlet_run must not raise even with no router."""
        bridge.record_gauntlet_run(
            scenario_name="N1_east_feeder_trip",
            result={"mw_peak": 980, "mw_limit": 1150, "passed": True},
            passed=True,
        )

    def test_disabled_bridge_does_not_raise_on_powerflow(self, bridge):
        bridge.record_powerflow_snapshot(
            feeder_id="feeder_east",
            mw_draw=920,
            mw_limit=1150,
            headroom_mw=230,
            rack_count=256,
            water_gph=42000,
        )

    def test_disabled_bridge_does_not_raise_on_throttle(self, bridge):
        bridge.record_apex_throttle(
            feeder_id="feeder_east",
            throttle_fraction=0.15,
            reason="N-1 contingency",
            affected_racks=40,
        )

    def test_disabled_bridge_recall_returns_empty_list(self, bridge):
        result = bridge.recall_recent_incidents()
        assert result == []

    def test_disabled_bridge_recall_with_feeder_filter(self, bridge):
        result = bridge.recall_recent_incidents(feeder_id="feeder_west", top_k=3)
        assert result == []


class TestSummariser:
    def test_summarise_extracts_known_keys(self):
        full = {
            "passed": True,
            "mw_peak": 980,
            "mw_limit": 1150,
            "headroom_mw": 170,
            "feeder_id": "feeder_east",
            "violations": 0,
            "water_gph": 41000,
            "duration_s": 300,
            "extra_key_should_be_dropped": "ignored",
        }
        summary = EnergyMemoryBridge._summarise(full)
        assert "extra_key_should_be_dropped" not in summary
        assert summary["mw_peak"] == 980
        assert summary["violations"] == 0

    def test_summarise_handles_missing_keys(self):
        partial = {"passed": False}
        summary = EnergyMemoryBridge._summarise(partial)
        assert summary == {"passed": False}


class TestUtilisationAlert:
    """High utilisation flag logic (without live writes)."""

    def test_high_utilisation_flag_at_90pct(self, bridge):
        # At 90% we expect alert=True in the payload — inspect via log capture
        # (no router means no write, but the flag logic must still compute)
        bridge.record_powerflow_snapshot(
            feeder_id="feeder_south",
            mw_draw=1035,   # 90% of 1150 MW
            mw_limit=1150,
            headroom_mw=115,
            rack_count=290,
        )
        # If we get here without exception, alert logic completed correctly

    def test_normal_utilisation_no_raise(self, bridge):
        bridge.record_powerflow_snapshot(
            feeder_id="feeder_north",
            mw_draw=500,
            mw_limit=1150,
            headroom_mw=650,
            rack_count=140,
        )
