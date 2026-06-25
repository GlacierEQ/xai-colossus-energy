# AGENTS.md

## Agent Instructions

This repo follows the Double Helix Architecture and Pro-Code 7-gate audit.

## Loading Order

1. AGENTS.md (this file)
2. HELIX.md (architecture)
3. PRO_CODE_AUDIT.md (quality gates)
4. README.md (overview)

## Subsystem Contract

Every module MUST expose:
- `tick()` — async method returning anomalies and actions
- `summary()` — sync method returning current state

## Engineering Laws

1. Sovereign Boundaries — No cross-subsystem imports
2. Contract First — Define interface before implementation
3. Graceful Degradation — Handle own failures
4. Telemetry First — Measure before managing
5. Scale Awareness — Design for 200k GPUs
6. Security by Default — Zero-trust at every boundary
7. Documentation as Code — Docs live with code
