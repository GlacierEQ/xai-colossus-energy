#!/usr/bin/env python3
"""Tests for Colossus Energy Grid Balancer — drive shipped energy.grid_balancer."""
from __future__ import annotations

import unittest

from energy.grid_balancer import GridBalancer, PowerSource, GridState


class TestGridBalancer(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.balancer = GridBalancer()

    async def test_initial_state_nominal(self) -> None:
        self.assertEqual(self.balancer.state, GridState.NOMINAL)

    async def test_tick_returns_valid_structure(self) -> None:
        result = await self.balancer.tick({"Z001": {"gpu_utilization": 0.8}}, 1)
        self.assertIn("anomalies", result)
        self.assertIn("actions", result)
        self.assertIn("state", result)
        self.assertIn("utilization_pct", result)

    async def test_utilization_calculation(self) -> None:
        result = await self.balancer.tick({"Z001": {"gpu_utilization": 1.0}}, 1)
        self.assertGreater(result["utilization_pct"], 0)

    async def test_headroom_positive(self) -> None:
        result = await self.balancer.tick({"Z001": {"gpu_utilization": 0.5}}, 1)
        self.assertGreater(result["headroom_mw"], 0)

    async def test_summary_structure(self) -> None:
        await self.balancer.tick({"Z001": {"gpu_utilization": 0.8}}, 1)
        s = self.balancer.summary()
        self.assertIn("state", s)
        self.assertIn("sources", s)
        self.assertGreater(len(s["sources"]), 0)

    def test_source_utilization(self) -> None:
        source = PowerSource("TEST", "utility", 100.0, current_output_mw=50.0)
        self.assertEqual(source.utilization_pct, 50.0)
        self.assertEqual(source.headroom_mw, 50.0)


if __name__ == "__main__":
    unittest.main()
