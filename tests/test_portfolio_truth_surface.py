from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

REQUIRED_PATHS = (
    "Cargo.toml",
    "src/lib.rs",
    "src/energy_optimizer.rs",
    "tests/energy_optimizer_rust.rs",
    "tests/test_energy_optimizer.py",
    "scripts/ci/verify_portfolio_core.sh",
)

FORBIDDEN_UNBOUNDED_CLAIMS = (
    "managing 150MW+ electrical loads",
    "Real-time MW telemetry tracking",
    "preventing transformer overloads",
    "Fully connected to APEX Highway mesh",
    "query_energy_pue()",
    "directly reduces operating costs by millions",
)


def test_readme_points_to_present_core_paths() -> None:
    text = README.read_text(encoding="utf-8")

    for relative_path in REQUIRED_PATHS:
        assert (ROOT / relative_path).exists(), relative_path
        assert relative_path in text


def test_readme_pins_the_complementary_child_repositories() -> None:
    text = README.read_text(encoding="utf-8")

    assert "69229edbb5fbf511c2416604bf77a8067235885e" in text
    assert "7919943e0b73f2ca8784e417ff9efb0cf8c37a86" in text
    assert "Alpha** owns stateless demand" in text
    assert "Omega** owns priority policy" in text


def test_readme_preserves_truth_and_non_affiliation_boundaries() -> None:
    text = README.read_text(encoding="utf-8")

    assert "not affiliated with xAI" in text
    assert "not evidence of operation" in text
    assert "scenario input only, not deployment evidence" in text
    assert "not a measured operating result" in text
    assert "not engineering evidence" in text


def test_unbounded_claims_do_not_return() -> None:
    text = README.read_text(encoding="utf-8")

    for claim in FORBIDDEN_UNBOUNDED_CLAIMS:
        assert claim not in text
