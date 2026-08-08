use std::error::Error;
use std::fmt::{Display, Formatter};

#[derive(Debug, Clone, PartialEq)]
pub struct ColossusPowerState {
    pub active_mw: f64,
    pub target_pue: f64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PowerStateError {
    NonFiniteActivePower,
    NegativeActivePower,
    NonFinitePue,
    PueBelowOne,
    NonFiniteCapacity,
    NegativeCapacity,
}

impl Display for PowerStateError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        let message = match self {
            Self::NonFiniteActivePower => "active power must be finite",
            Self::NegativeActivePower => "active power cannot be negative",
            Self::NonFinitePue => "target PUE must be finite",
            Self::PueBelowOne => "target PUE cannot be below 1.0",
            Self::NonFiniteCapacity => "facility capacity must be finite",
            Self::NegativeCapacity => "facility capacity cannot be negative",
        };
        formatter.write_str(message)
    }
}

impl Error for PowerStateError {}

impl ColossusPowerState {
    pub const DEFAULT_TARGET_PUE: f64 = 1.08;

    /// Backward-compatible constructor for the original 1.08 scenario.
    ///
    /// Use `try_new` whenever inputs come from an external or untrusted source.
    pub fn new(active_mw: f64) -> Self {
        Self::try_new(active_mw, Self::DEFAULT_TARGET_PUE)
            .expect("ColossusPowerState::new requires finite, non-negative active power")
    }

    pub fn try_new(active_mw: f64, target_pue: f64) -> Result<Self, PowerStateError> {
        if !active_mw.is_finite() {
            return Err(PowerStateError::NonFiniteActivePower);
        }
        if active_mw < 0.0 {
            return Err(PowerStateError::NegativeActivePower);
        }
        if !target_pue.is_finite() {
            return Err(PowerStateError::NonFinitePue);
        }
        if target_pue < 1.0 {
            return Err(PowerStateError::PueBelowOne);
        }

        Ok(Self {
            active_mw,
            target_pue,
        })
    }

    /// Scenario cooling and facility overhead implied by PUE.
    pub fn compute_cooling_overhead_mw(&self) -> f64 {
        self.active_mw * (self.target_pue - 1.0)
    }

    /// Total facility input required by the current scenario.
    pub fn facility_input_mw(&self) -> f64 {
        self.active_mw + self.compute_cooling_overhead_mw()
    }

    /// Remaining facility capacity after active load and modeled overhead.
    /// Negative output represents a scenario shortfall, not a control action.
    pub fn headroom_mw(&self, capacity_mw: f64) -> Result<f64, PowerStateError> {
        if !capacity_mw.is_finite() {
            return Err(PowerStateError::NonFiniteCapacity);
        }
        if capacity_mw < 0.0 {
            return Err(PowerStateError::NegativeCapacity);
        }

        Ok(capacity_mw - self.facility_input_mw())
    }
}
