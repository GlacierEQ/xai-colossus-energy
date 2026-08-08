use colossus_energy_model::{ColossusPowerState, PowerStateError};

const EPSILON: f64 = 1e-9;

#[test]
fn default_scenario_preserves_the_original_overhead_formula() {
    let state = ColossusPowerState::new(150.0);

    assert!((state.compute_cooling_overhead_mw() - 12.0).abs() < EPSILON);
    assert!((state.facility_input_mw() - 162.0).abs() < EPSILON);
}

#[test]
fn explicit_pue_produces_reviewable_headroom() {
    let state = ColossusPowerState::try_new(80.0, 1.10).unwrap();

    assert!((state.compute_cooling_overhead_mw() - 8.0).abs() < EPSILON);
    assert!((state.headroom_mw(100.0).unwrap() - 12.0).abs() < EPSILON);
}

#[test]
fn negative_headroom_is_a_scenario_shortfall() {
    let state = ColossusPowerState::try_new(95.0, 1.10).unwrap();

    assert!((state.headroom_mw(100.0).unwrap() + 4.5).abs() < EPSILON);
}

#[test]
fn rejects_non_finite_or_negative_active_power() {
    assert_eq!(
        ColossusPowerState::try_new(f64::NAN, 1.08),
        Err(PowerStateError::NonFiniteActivePower)
    );
    assert_eq!(
        ColossusPowerState::try_new(-1.0, 1.08),
        Err(PowerStateError::NegativeActivePower)
    );
}

#[test]
fn rejects_invalid_pue() {
    assert_eq!(
        ColossusPowerState::try_new(10.0, f64::INFINITY),
        Err(PowerStateError::NonFinitePue)
    );
    assert_eq!(
        ColossusPowerState::try_new(10.0, 0.99),
        Err(PowerStateError::PueBelowOne)
    );
}

#[test]
fn rejects_invalid_capacity() {
    let state = ColossusPowerState::new(10.0);

    assert_eq!(
        state.headroom_mw(f64::NAN),
        Err(PowerStateError::NonFiniteCapacity)
    );
    assert_eq!(
        state.headroom_mw(-1.0),
        Err(PowerStateError::NegativeCapacity)
    );
}
