# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
#!/usr/bin/env python3
"""Quick memory health check for xai-colossus-energy.

Usage:
    python scripts/run_memory_health.py
    python scripts/run_memory_health.py --fail-on-degraded
"""
import sys
import argparse

sys.path.insert(0, ".")

from src.memory.memory_bridge import EnergyMemoryBridge


def main():
    parser = argparse.ArgumentParser(description="Energy memory layer health check")
    parser.add_argument("--fail-on-degraded", action="store_true",
                        help="Exit 1 if any backend is degraded (for CI)")
    args = parser.parse_args()

    bridge = EnergyMemoryBridge()
    health = bridge.health()

    print("\n╔══════════════════════════════════════════╗")
    print("║   xai-colossus-energy  Memory Health     ║")
    print("╚══════════════════════════════════════════╝")

    all_ok = True
    for backend, status in health.items():
        icon = "✅" if status in ("ok", "healthy") else "⚠️ "
        if status not in ("ok", "healthy"):
            all_ok = False
        print(f"  {icon}  {backend:<20} {status}")

    print()
    if all_ok:
        print("  ✅  All memory backends healthy")
    else:
        print("  ⚠️   One or more backends degraded")

    if args.fail_on_degraded and not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
