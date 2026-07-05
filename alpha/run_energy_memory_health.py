#!/usr/bin/env python3
"""
Energy Memory Health Check
==========================
Verifies the EnergyMemoryBridge can reach both Pinecone and Supermemory.

Usage:
    python scripts/run_energy_memory_health.py
    python scripts/run_energy_memory_health.py --fail-on-degraded

Exit codes:
    0  All backends healthy
    1  One or more backends degraded (only fails with --fail-on-degraded)
    2  Critical error
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.memory.energy_memory_bridge import EnergyMemoryBridge


def main():
    parser = argparse.ArgumentParser(description="Energy memory layer health check")
    parser.add_argument(
        "--fail-on-degraded",
        action="store_true",
        help="Exit 1 if any backend is degraded (use in CI)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args()

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "repo": "xai-colossus-energy",
        "checks": [],
    }

    bridge = EnergyMemoryBridge()
    router_available = bridge._router is not None

    # Check 1: MemoryRouter availability
    report["checks"].append({
        "name": "memory_router_available",
        "status": "pass" if router_available else "degraded",
        "detail": "colossus-gateway MemoryRouter loaded" if router_available
                  else "MemoryRouter not found — set COLOSSUS_GATEWAY_PATH",
    })

    # Check 2: Dry-run write (no router = skip gracefully)
    write_ok = False
    try:
        bridge.record_powerflow_snapshot(
            feeder_id="health_check",
            mw_draw=0.0,
            mw_limit=1150.0,
            headroom_mw=1150.0,
            rack_count=0,
        )
        write_ok = True
    except Exception as exc:
        report["checks"].append({
            "name": "dry_run_powerflow_write",
            "status": "error",
            "detail": str(exc),
        })

    if write_ok:
        report["checks"].append({
            "name": "dry_run_powerflow_write",
            "status": "pass" if router_available else "skipped",
            "detail": "write completed" if router_available else "skipped (no router)",
        })

    # Check 3: Recall
    try:
        results = bridge.recall_recent_incidents(top_k=1)
        report["checks"].append({
            "name": "recall_recent_incidents",
            "status": "pass",
            "detail": f"returned {len(results)} result(s)",
        })
    except Exception as exc:
        report["checks"].append({
            "name": "recall_recent_incidents",
            "status": "error",
            "detail": str(exc),
        })

    # Summary
    statuses = [c["status"] for c in report["checks"]]
    report["overall"] = "pass" if all(s in ("pass", "skipped") for s in statuses) else "degraded"

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"  Energy Memory Health — {report['timestamp']}")
        print(f"  Overall: {report['overall'].upper()}")
        print(f"{'='*60}")
        for check in report["checks"]:
            icon = {"pass": "✅", "degraded": "⚠️", "skipped": "⏭️", "error": "❌"}.get(check["status"], "?")
            print(f"  {icon}  {check['name']}: {check['detail']}")
        print()

    if args.fail_on_degraded and report["overall"] != "pass":
        sys.exit(1)


if __name__ == "__main__":
    main()
