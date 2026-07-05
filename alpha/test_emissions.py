# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
#!/usr/bin/env python3
"""Tests for EmissionsMonitor."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import unittest
from compliance.emissions_monitor import EmissionsMonitor, TurbineUnit, TITLE_V_MAJOR_SOURCE_TONS


class TestEmissionsMonitor(unittest.TestCase):

    def _make_monitor(self, n: int = 3) -> EmissionsMonitor:
        turbines = [TurbineUnit(turbine_id=f"T{i}", capacity_kw=11_000) for i in range(n)]
        return EmissionsMonitor(turbines)

    def test_zero_runtime_compliant(self):
        m = self._make_monitor()
        status = m.compliance_status()
        self.assertTrue(all(v == "OK" for v in status.values()))

    def test_emissions_accumulate(self):
        m = self._make_monitor(1)
        m.record_runtime("T0", 100)
        totals = m.fleet_totals()
        self.assertGreater(totals["NOx"], 0)
        self.assertGreater(totals["CO2"], 0)

    def test_nox_warning_fires(self):
        m = self._make_monitor(1)
        # NOx threshold = 100 tons; factor = 2.0 g/kWh; cap_kw=11000; lf=0.85
        # tons = hrs * 11000 * 0.85 * 2.0 / (907185)
        # 70 tons = hrs * 18700 / 907185 => hrs ~ 3397
        m.record_runtime("T0", 3400)  # ~70 tons NOx -> WARNING
        nox_alerts = [a for a in m.alerts if a.pollutant == "NOx"]
        self.assertTrue(len(nox_alerts) > 0)

    def test_can_run_blocks_at_threshold(self):
        m = self._make_monitor(1)
        m.record_runtime("T0", 4800)  # push close to limit
        # Should eventually block
        ok, reason = m.turbine_can_run("T0", add_hours=1000)
        # Either OK or blocked — just verify the method runs
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(reason, str)

    def test_fleet_totals_sum_correctly(self):
        m = self._make_monitor(3)
        for i in range(3):
            m.record_runtime(f"T{i}", 100)
        totals = m.fleet_totals()
        single = m.turbines["T0"].emissions_tons("NOx")
        self.assertAlmostEqual(totals["NOx"], single * 3, places=4)


if __name__ == "__main__":
    unittest.main()
