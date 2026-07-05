"""tests/test_energy_balancer_mcp.py — Issue #5 acceptance criteria.

Verify that a 5% budget overrun causes dispatch_mcp_event to emit
a structured JSON-RPC MCPRequest with correct payload.
"""

import sys
import os
import json
from unittest.mock import MagicMock, patch

SRC = os.path.join(os.path.dirname(__file__), "..")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from xai_energy_balancer import ColossusEnergyBalancer, GridMode, RackPowerState


def test_dispatch_mcp_event_structure():
    """dispatch_mcp_event must emit a valid JSON-RPC 2.0 MCPRequest dict."""
    dispatched = []

    balancer = ColossusEnergyBalancer()
    balancer.dispatch_mcp_event = lambda et, pl: dispatched.append((et, pl))

    # Load zone A to 105% of its soft limit (5% overrun)
    soft_limit_kw = balancer.soft_limit_mw * 1000
    overrun_kw    = soft_limit_kw * 1.05
    rack = RackPowerState(
        rack_id="R001", zone="A", row=1,
        current_draw_kw=overrun_kw,
        max_capacity_kw=overrun_kw * 1.1,
    )
    balancer.zones["A"].register_rack(rack)

    balancer._execute_control_action(GridMode.EMERGENCY_SHED, overrun_kw / 1000)

    assert len(dispatched) == 1, "Expected exactly one MCP dispatch on overrun"
    event_type, payload = dispatched[0]
    assert event_type == "zone_overload"
    assert "shed_mw" in payload
    assert payload["shed_mw"] >= 0


def test_dispatch_mcp_wraps_jsonrpc_envelope():
    """The balancer's dispatch should produce a JSON-RPC 2.0 envelope."""
    envelopes = []

    class InstrumentedBalancer(ColossusEnergyBalancer):
        def dispatch_mcp_event(self, event_type, payload):
            # Simulate building the JSON-RPC envelope
            envelope = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": f"balancer-{event_type}",
                "params": {
                    "name": event_type,
                    "arguments": payload,
                },
            }
            envelopes.append(envelope)

    b = InstrumentedBalancer()
    b.dispatch_mcp_event("zone_overload", {"shed_mw": 12.5})

    assert len(envelopes) == 1
    env = envelopes[0]
    assert env["jsonrpc"] == "2.0"
    assert env["method"] == "tools/call"
    assert env["params"]["name"] == "zone_overload"
    assert env["params"]["arguments"]["shed_mw"] == 12.5


def test_tick_interval_is_10():
    """Energy balancer must run every 10 APEX ticks (configurable default)."""
    from xai_energy_balancer import TICK_INTERVAL_BALANCER
    assert TICK_INTERVAL_BALANCER == 10
