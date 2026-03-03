# Policy: Risk tiers + required checks

This project follows a **single-contract** approach: the file `control/contract.yml` is the source of truth for:

- **risk tiers** (determined by changed file paths)
- **required checks** per tier
- **docs drift rules** for changes to the control plane

## Why

The goal is to make the repo **agent-friendly** and **machine-verifiable**:

- A coding agent can propose changes
- CI can deterministically decide what must run before merge
- Review tooling can remain pluggable while policy semantics stay stable

## Risk tiers (default)

| Tier | Typical changes | Required checks |
|------|------------------|-----------------|
| low | docs-only changes | lint, unit-tests |
| medium | code changes | lint, typecheck, unit-tests |
| high | CI / policy / control-plane changes | lint, typecheck, unit-tests, security |

> Adjust tiers for your org (e.g., add `infra/**` or `prod/**` patterns).

## Docs drift rules

Some changes require documentation updates. Example rule:

- If `control/contract.yml` changes, then `docs/POLICY.md` must also change.

This prevents “silent drift” where CI rules evolve but docs do not.

## CI integration

The workflow `.github/workflows/ci.yml` runs:

1. **preflight** job: runs `scripts/risk_policy_gate.py`
2. fanout jobs (lint, typecheck, tests, etc.) depend on preflight and run conditionally

