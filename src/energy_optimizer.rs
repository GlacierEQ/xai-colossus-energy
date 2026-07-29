pub struct ColossusPowerState {
    pub active_mw: f64,
    pub target_pue: f64,
}

impl ColossusPowerState {
    pub fn new(mw: f64) -> Self {
        ColossusPowerState {
            active_mw: mw,
            target_pue: 1.08,
        }
    }

    pub fn compute_cooling_overhead_mw(&self) -> f64 {
        self.active_mw * (self.target_pue - 1.0)
    }
}
