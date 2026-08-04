# Colossus Energy Scenario Model and Control-Family Gate

An independent portfolio project for modeling compute-facility electrical demand, PUE-derived overhead, reserve headroom, and priority-aware response under a simulated power shortfall.

This repository is **not affiliated with xAI**, does not use proprietary xAI or utility data, and is not evidence of operation inside Colossus, a power grid, or a production datacenter.

## What is implemented

### Native Rust scenario model

[`src/energy_optimizer.rs`](src/energy_optimizer.rs) provides:

- validated active-power and target-PUE inputs;
- modeled facility overhead derived from PUE;
- modeled facility input power;
- capacity headroom or shortfall calculation;
- explicit errors for non-finite, negative, or invalid values.

[`Cargo.toml`](Cargo.toml), [`src/lib.rs`](src/lib.rs), and [`tests/energy_optimizer_rust.rs`](tests/energy_optimizer_rust.rs) make the Rust logic directly compilable and testable.

### Python reference formula

[`tests/test_energy_optimizer.py`](tests/test_energy_optimizer.py) checks the documented formula independently in Python. It is a parity reference and does **not** substitute for executing the Rust tests.

### Pinned Alpha/Omega family verification

The repository-owned verifier [`scripts/ci/verify_portfolio_core.sh`](scripts/ci/verify_portfolio_core.sh) checks out and executes:

- [`xai-colossus-energy-alpha`](https://github.com/GlacierEQ/xai-colossus-energy-alpha) at commit `69229edbb5fbf511c2416604bf77a8067235885e`;
- [`xai-colossus-energy-omega`](https://github.com/GlacierEQ/xai-colossus-energy-omega) at commit `7919943e0b73f2ca8784e417ff9efb0cf8c37a86`.

Alpha calculates scenario demand, reserve, and headroom. Omega orders simulated load-shed actions. The verifier runs their own tests and one cross-repository scenario in which a quantified shortfall is handed to the controller without copying either child implementation into this repository.

## Fastest reproducible review

### Rust model

```bash
cargo fmt --check
cargo test --all-targets
```

### Local Python reference and truth-surface tests

```bash
python -m pip install pytest
python -m pytest \
  tests/test_energy_optimizer.py \
  tests/test_portfolio_truth_surface.py \
  -q
```

### Complete bounded family gate

```bash
bash scripts/ci/verify_portfolio_core.sh
```

The family gate requires network access to fetch the two public sibling repositories at the pinned commits.

## Architecture

```text
Rust scenario model
  active MW + target PUE + facility capacity
                    │
                    ▼
       modeled overhead and headroom

Pinned Energy Alpha
  loads + capacity + reserve fraction
                    │
                    ▼
       explicit scenario power budget
                    │
                    ▼
Pinned Energy Omega
  shortfall + circuit priorities
                    │
                    ▼
       ordered simulated shed actions
```

The Rust model and Alpha model overlap conceptually but serve different verification purposes. Rust demonstrates a typed native model; Alpha/Omega demonstrate a separated analytical-and-control family. They are not represented as one production runtime.

## Evidence state

| Capability | Current evidence state |
|---|---|
| Rust PUE-derived overhead model | Source and native tests present |
| Rust validation and headroom calculation | Source and native tests present |
| Python formula parity checks | Source and tests present |
| Alpha budget model | Pinned source and tests executed by the family verifier |
| Omega priority controller | Pinned source and tests executed by the family verifier |
| Alpha-to-Omega shortfall scenario | Pinned cross-repository integration assertion in the verifier |
| Real-time MW telemetry | Not implemented or verified by the inspected core |
| Grid or utility demand-response integration | Not implemented or verified by the inspected core |
| Transformer protection | Not implemented or verified by the inspected core |
| Production load shedding | Not implemented or verified |
| 150 MW or larger operation | A documented scenario input only, not deployment evidence |
| PUE 1.08 | A configurable scenario default, not a measured operating result |
| MCP, Mastermind, or APEX live connectivity | Not established by the inspected core |
| Operating-cost reduction | Not measured or verified |

## Alpha/Omega boundary

The child repositories are complementary, not automatically duplicates:

- **Alpha** owns stateless demand, reserve, and headroom calculation.
- **Omega** owns priority policy and simulated response.

Both currently retain historical `answer = 42` fields, and Alpha includes a synthetic confidence value. The family verifier deliberately ignores those fields because they are not engineering evidence. Future hardening should remove or quarantine them from the operational data contract while preserving repository history.

## Safety and interpretation

- Negative headroom means a simulated scenario shortfall; it does not authorize a real control action.
- Load-shed output is a portfolio demonstration and must not be applied to physical infrastructure.
- PUE is used as an input to a simple scenario formula; this repository does not model complete electrical distribution, UPS behavior, transformer constraints, thermal coupling, tariffs, grid services, or failure propagation.
- Inputs from telemetry, operators, agents, or external systems require separate authentication, validation, units, freshness, and authority controls.

## Promotion requirements

Before this family is presented as operational energy infrastructure, it still needs:

1. removal or quarantine of historical theatrical output fields in Alpha and Omega;
2. typed, versioned schemas for loads, circuits, capacities, units, and timestamps;
3. boundary and property tests for reserve fractions, priorities, ties, partial shedding, and impossible shortfalls;
4. deterministic replay fixtures and failure injection;
5. authenticated adapter tests for any external telemetry or control plane;
6. disclosed benchmark environments for latency, scale, reliability, or cost claims;
7. independent domain review before any physical-infrastructure interpretation.

## Authorship and use

Independent portfolio work by Casey Barton / GlacierEQ. Company and product names identify the engineering problem space only; they do not imply employment, endorsement, partnership, insider access, proprietary information, or production deployment.
