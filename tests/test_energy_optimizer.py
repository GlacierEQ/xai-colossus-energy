"""Python reference checks for the documented PUE scenario formula.

These tests do not execute Rust. Native Rust behavior is verified by
``cargo test --all-targets`` and ``tests/energy_optimizer_rust.rs``.
"""

import math

import pytest


def modeled_overhead_mw(active_mw: float, target_pue: float) -> float:
    if not math.isfinite(active_mw) or active_mw < 0:
        raise ValueError("active_mw must be finite and non-negative")
    if not math.isfinite(target_pue) or target_pue < 1.0:
        raise ValueError("target_pue must be finite and at least 1.0")
    return active_mw * (target_pue - 1.0)


def test_documented_150_mw_reference_scenario() -> None:
    assert modeled_overhead_mw(150.0, 1.08) == pytest.approx(12.0)


def test_pue_one_has_no_modeled_overhead() -> None:
    assert modeled_overhead_mw(25.0, 1.0) == 0.0


def test_reference_formula_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        modeled_overhead_mw(-1.0, 1.08)
    with pytest.raises(ValueError):
        modeled_overhead_mw(10.0, 0.99)
