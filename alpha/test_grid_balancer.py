# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
#!/usr/bin/env python3
"""Tests for Colossus Energy Grid Balancer"""
import asyncio
import pytest
from energy.grid_balancer import GridBalancer, PowerSource, GridState


@pytest.fixture
def balancer():
    return GridBalancer()


class TestGridBalancer:
    @pytest.mark.asyncio
    async def test_initial_state_nominal(self, balancer):
        assert balancer.state == GridState.NOMINAL

    @pytest.mark.asyncio
    async def test_tick_returns_valid_structure(self, balancer):
        result = await balancer.tick({"Z001": {"gpu_utilization": 0.8}}, 1)
        assert "anomalies" in result
        assert "actions" in result
        assert "state" in result
        assert "utilization_pct" in result

    @pytest.mark.asyncio
    async def test_utilization_calculation(self, balancer):
        result = await balancer.tick({"Z001": {"gpu_utilization": 1.0}}, 1)
        assert result["utilization_pct"] > 0

    @pytest.mark.asyncio
    async def test_headroom_positive(self, balancer):
        result = await balancer.tick({"Z001": {"gpu_utilization": 0.5}}, 1)
        assert result["headroom_mw"] > 0

    @pytest.mark.asyncio
    async def test_summary_structure(self, balancer):
        await balancer.tick({"Z001": {"gpu_utilization": 0.8}}, 1)
        s = balancer.summary()
        assert "state" in s
        assert "sources" in s
        assert len(s["sources"]) > 0

    def test_source_utilization(self):
        source = PowerSource("TEST", "utility", 100.0, current_output_mw=50.0)
        assert source.utilization_pct == 50.0
        assert source.headroom_mw == 50.0
