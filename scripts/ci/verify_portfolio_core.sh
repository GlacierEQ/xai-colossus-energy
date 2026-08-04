#!/usr/bin/env bash
set -euo pipefail

ALPHA_SHA="69229edbb5fbf511c2416604bf77a8067235885e"
OMEGA_SHA="7919943e0b73f2ca8784e417ff9efb0cf8c37a86"
ARTIFACT_DIR=".verification-artifacts"
SIBLING_DIR="${RUNNER_TEMP:-/tmp}/colossus-energy-family"

rm -rf "${SIBLING_DIR}"
mkdir -p "${ARTIFACT_DIR}" "${SIBLING_DIR}"

python -m pip install --disable-pip-version-check pytest

cargo fmt --check
cargo test --all-targets \
  | tee "${ARTIFACT_DIR}/cargo-test.txt"

python -m pytest \
  tests/test_energy_optimizer.py \
  tests/test_portfolio_truth_surface.py \
  -q \
  | tee "${ARTIFACT_DIR}/python-local-tests.txt"

checkout_exact() {
  local repository="$1"
  local commit="$2"
  local destination="$3"

  git init -q "${destination}"
  git -C "${destination}" remote add origin "https://github.com/GlacierEQ/${repository}.git"
  git -C "${destination}" fetch -q --depth 1 origin "${commit}"
  git -C "${destination}" checkout -q --detach FETCH_HEAD

  local resolved
  resolved="$(git -C "${destination}" rev-parse HEAD)"
  if [[ "${resolved}" != "${commit}" ]]; then
    echo "Pinned commit mismatch for ${repository}: expected ${commit}, got ${resolved}" >&2
    exit 67
  fi
}

checkout_exact "xai-colossus-energy-alpha" "${ALPHA_SHA}" "${SIBLING_DIR}/alpha"
checkout_exact "xai-colossus-energy-omega" "${OMEGA_SHA}" "${SIBLING_DIR}/omega"

python -m pytest "${SIBLING_DIR}/alpha/tests/test_power_budget.py" -q \
  | tee "${ARTIFACT_DIR}/alpha-tests.txt"
python -m pytest "${SIBLING_DIR}/omega/tests/test_load_shed.py" -q \
  | tee "${ARTIFACT_DIR}/omega-tests.txt"

ALPHA_SRC="${SIBLING_DIR}/alpha/src" \
OMEGA_SRC="${SIBLING_DIR}/omega/src" \
ALPHA_SHA="${ALPHA_SHA}" \
OMEGA_SHA="${OMEGA_SHA}" \
python - <<'PY' | tee ".verification-artifacts/family-integration.json"
import json
import os
import sys
from pathlib import Path

alpha_src = Path(os.environ["ALPHA_SRC"])
omega_src = Path(os.environ["OMEGA_SRC"])
sys.path.insert(0, str(alpha_src))
sys.path.insert(0, str(omega_src))

from power_budget import Load, budget  # type: ignore  # noqa: E402
from load_shed import Circuit, shed  # type: ignore  # noqa: E402

loads = [
    Load("inference", 40.0, True),
    Load("batch-training", 20.0, False),
    Load("cooling", 8.0, True),
]
result = budget(loads, capacity_mw=70.0, reserve_frac=0.08)
shortfall_mw = max(0.0, -result["headroom_mw"])

control = shed(
    [
        Circuit("inference", 40.0, 1),
        Circuit("cooling", 8.0, 2),
        Circuit("batch-training", 20.0, 9),
    ],
    shortfall_mw,
)

assert result["status"] == "OVERSUBSCRIBED", result
assert shortfall_mw == 3.6, shortfall_mw
assert control["met"] is True, control
assert control["actions"][0]["shed"] == "batch-training", control
assert control["freed_mw"] == 20.0, control

receipt = {
    "schema": "glaciereq.energy-family-integration.v1",
    "alpha": {
        "repository": "GlacierEQ/xai-colossus-energy-alpha",
        "commit": os.environ["ALPHA_SHA"],
        "status": result["status"],
        "used_mw": result["used_mw"],
        "reserve_mw": result["reserve_mw"],
        "headroom_mw": result["headroom_mw"],
    },
    "omega": {
        "repository": "GlacierEQ/xai-colossus-energy-omega",
        "commit": os.environ["OMEGA_SHA"],
        "need_mw": shortfall_mw,
        "first_action": control["actions"][0],
        "freed_mw": control["freed_mw"],
        "met": control["met"],
    },
    "evidence_state": "PINNED_CROSS_REPOSITORY_SCENARIO_VERIFIED",
    "limits": [
        "simulation only",
        "no grid connection",
        "no live telemetry",
        "no hardware control",
        "historical answer and confidence fields are not used as evidence",
    ],
}
print(json.dumps(receipt, indent=2))
PY

GITHUB_SOURCE_HEAD="${GITHUB_HEAD_SHA:-${GITHUB_SHA:-local}}" \
ALPHA_SHA="${ALPHA_SHA}" \
OMEGA_SHA="${OMEGA_SHA}" \
python - <<'PY'
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path

artifact_dir = Path(".verification-artifacts")
receipt = {
    "schema": "glaciereq.energy.portfolio-core-receipt.v1",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "repository": os.environ.get("GITHUB_REPOSITORY", "GlacierEQ/xai-colossus-energy"),
    "tested_commit_or_merge_ref": os.environ.get("GITHUB_SHA", "local"),
    "source_head_commit": os.environ["GITHUB_SOURCE_HEAD"],
    "python": platform.python_version(),
    "rust": "cargo test --all-targets passed",
    "alpha_commit": os.environ["ALPHA_SHA"],
    "omega_commit": os.environ["OMEGA_SHA"],
    "evidence_state": "BOUNDED_ENERGY_FAMILY_TEST_VERIFIED",
    "verified": [
        "native Rust scenario model",
        "local truth surface",
        "pinned Alpha budget tests",
        "pinned Omega load-shed tests",
        "pinned budget-to-controller integration scenario",
    ],
    "not_verified": [
        "real grid or utility integration",
        "real-time telemetry",
        "transformer protection",
        "production load shedding",
        "150 MW or larger deployment",
        "PUE improvement",
        "operating-cost reduction",
        "MCP or APEX live connectivity",
    ],
}
(artifact_dir / "portfolio-core-receipt.json").write_text(
    json.dumps(receipt, indent=2) + "\n",
    encoding="utf-8",
)
PY
