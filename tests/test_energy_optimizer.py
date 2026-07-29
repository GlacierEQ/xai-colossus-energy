"""Test suite for Colossus Energy Optimizer."""
import unittest

class ColossusPowerStateSim:
    def __init__(self, mw: float):
        self.active_mw = mw
        self.target_pue = 1.08

    def compute_cooling_overhead_mw(self) -> float:
        return self.active_mw * (self.target_pue - 1.0)

class TestEnergyOptimizer(unittest.TestCase):
    def test_cooling_overhead(self):
        st = ColossusPowerStateSim(150.0)
        oh = st.compute_cooling_overhead_mw()
        self.assertAlmostEqual(oh, 12.0, delta=0.01)

if __name__ == "__main__":
    unittest.main()
