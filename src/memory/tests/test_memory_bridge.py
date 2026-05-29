"""Unit tests for EnergyMemoryBridge (no live backends required)."""
import time
import unittest
from unittest.mock import MagicMock, patch

# Patch before import to avoid live SDK calls
with patch.dict("os.environ", {"COLOSSUS_GATEWAY_PATH": "/nonexistent"}), \
     patch("builtins.__import__", side_effect=ImportError):
    pass  # pre-condition

from src.memory.memory_bridge import EnergyMemoryBridge, EnergyScenario


def make_scenario(**overrides) -> EnergyScenario:
    defaults = dict(
        scenario_id="test-001",
        scenario_type="gauntlet",
        timestamp=time.time(),
        total_mw=920.0,
        feeder_headroom_mw=80.0,
        grid_limit_mw=1000.0,
        safe=True,
        throttle_fraction=0.0,
        emissions_proxy_kg_co2=1200.0,
        water_use_gallons=45000.0,
        affected_zip_codes=["38109", "38671"],
        notes="nominal run",
    )
    defaults.update(overrides)
    return EnergyScenario(**defaults)


class TestEnergyMemoryBridgeDegraded(unittest.TestCase):
    """Tests for bridge with no gateway installed."""

    def setUp(self):
        self.bridge = EnergyMemoryBridge()
        self.bridge._router = None  # force degraded mode

    def test_remember_scenario_degraded_returns_false(self):
        result = self.bridge.remember_scenario(make_scenario())
        self.assertFalse(result)

    def test_record_throttle_degraded_returns_false(self):
        result = self.bridge.record_throttle_decision("test-001", "feeder limit", 0.25)
        self.assertFalse(result)

    def test_recall_degraded_returns_empty_list(self):
        result = self.bridge.recall_similar("feeder overload")
        self.assertEqual(result, [])

    def test_health_degraded(self):
        health = self.bridge.health()
        self.assertIn("unavailable", health.values())


class TestEnergyMemoryBridgeWithRouter(unittest.TestCase):
    """Tests for bridge with a mocked MemoryRouter."""

    def setUp(self):
        self.bridge = EnergyMemoryBridge()
        self.mock_router = MagicMock()
        self.bridge._router = self.mock_router

    def test_remember_scenario_calls_router(self):
        self.mock_router.remember_scenario.return_value = True
        scenario = make_scenario(scenario_id="gs-002", safe=False, throttle_fraction=0.5)
        result = self.bridge.remember_scenario(scenario)
        self.assertTrue(result)
        self.mock_router.remember_scenario.assert_called_once()
        call_kwargs = self.mock_router.remember_scenario.call_args.kwargs
        self.assertEqual(call_kwargs["scenario_id"], "gs-002")
        self.assertEqual(call_kwargs["namespace"], "colossus-scenarios")

    def test_unsafe_scenario_metadata_flag(self):
        self.mock_router.remember_scenario.return_value = True
        self.bridge.remember_scenario(make_scenario(safe=False))
        metadata = self.mock_router.remember_scenario.call_args.kwargs["metadata"]
        self.assertFalse(metadata["safe"])

    def test_record_throttle_decision(self):
        self.mock_router.record_decision.return_value = True
        result = self.bridge.record_throttle_decision(
            "gs-003", "substation limit hit", 0.30, "gauntlet"
        )
        self.assertTrue(result)
        content = self.mock_router.record_decision.call_args.kwargs["content"]
        self.assertIn("30%", content)
        self.assertIn("substation limit hit", content)

    def test_recall_passes_namespace(self):
        self.mock_router.recall.return_value = [{"id": "gs-001", "score": 0.92}]
        results = self.bridge.recall_similar("Memphis heatwave feeder overload")
        self.assertEqual(len(results), 1)
        call_kwargs = self.mock_router.recall.call_args.kwargs
        self.assertEqual(call_kwargs["namespace"], "colossus-scenarios")

    def test_recall_safe_filter(self):
        self.mock_router.recall.return_value = []
        self.bridge.recall_similar("cooling trip", filter_safe_only=True)
        call_kwargs = self.mock_router.recall.call_args.kwargs
        self.assertEqual(call_kwargs["filter"], {"safe": True})

    def test_router_exception_returns_false(self):
        self.mock_router.remember_scenario.side_effect = RuntimeError("Pinecone timeout")
        result = self.bridge.remember_scenario(make_scenario())
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
