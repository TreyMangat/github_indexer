#!/usr/bin/env python3

"""
risk_policy_gate.py

Preflight policy gate inspired by the "Code Factory" control-plane pattern:
- A single machine-readable contract defines risk tiers + required checks.
- This script evaluates the *changed files* and outputs the selected tier and checks.
- It can also enforce docs drift rules.

Intended usage:
- Local:
    python scripts/risk_policy_gate.py --base main --head HEAD

- GitHub Actions:
    python scripts/risk_policy_gate.py --github-output "$GITHUB_OUTPUT"

Contract file:
- control/contract.yml
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterable

import yaml


@dataclass(frozen=True)
class RiskTier:
    name: str
    priority: int
    match: list[str]
    required_checks: list[str]


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr}")
    return proc.stdout


def _git_changed_files(base: str, head: str, repo_root: Path) -> list[str]:
    # Use triple-dot to compare merge base..head
    out = _run(["git", "diff", "--name-only", f"{base}...{head}"], cwd=repo_root)
    files = [line.strip() for line in out.splitlines() if line.strip()]
    return files


def _load_contract(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Contract YAML must be a mapping.")
    return data


def _parse_tiers(contract: dict[str, Any]) -> list[RiskTier]:
    tiers_raw = contract.get("risk_tiers", [])
    tiers: list[RiskTier] = []
    for t in tiers_raw:
        tiers.append(
            RiskTier(
                name=str(t["name"]),
                priority=int(t.get("priority", 0)),
                match=[str(p) for p in t.get("match", [])],
                required_checks=[str(c) for c in t.get("required_checks", [])],
            )
        )
    if not tiers:
        raise ValueError("No risk_tiers found in contract.")
    return sorted(tiers, key=lambda x: x.priority)


def _tier_for_files(tiers: list[RiskTier], changed_files: Iterable[str]) -> RiskTier:
    matched: list[RiskTier] = []
    files = list(changed_files)
    for tier in tiers:
        for f in files:
            if any(fnmatch(f, pat) for pat in tier.match):
                matched.append(tier)
                break
    # If nothing matches, pick lowest priority tier (safe default)
    if not matched:
        return tiers[0]
    return max(matched, key=lambda t: t.priority)


def _changed_set(changed_files: list[str]) -> set[str]:
    # Normalize to POSIX-style paths for pattern matching
    return {f.replace("\\", "/") for f in changed_files}


def _enforce_docs_drift(contract: dict[str, Any], changed_files: list[str]) -> list[str]:
    """Return a list of violations (strings)."""
    violations: list[str] = []
    changed = _changed_set(changed_files)

    for rule in contract.get("docs_drift_rules", []) or []:
        rule_name = str(rule.get("name", "unnamed_rule"))
        when_changed = [str(p) for p in rule.get("when_changed", [])]
        require_updated = [str(p) for p in rule.get("require_updated", [])]

        # If any trigger file changed, then required files must also be changed.
        triggered = any(any(fnmatch(f, pat) for pat in when_changed) for f in changed)
        if triggered:
            for required in require_updated:
                required_ok = any(fnmatch(f, required) for f in changed)
                if not required_ok:
                    violations.append(
                        f"{rule_name}: {required} must be updated when {when_changed} changes."
                    )
    return violations


def _write_github_output(path: Path, data: dict[str, str]) -> None:
    # GitHub Actions output format: KEY=VALUE per line
    lines = [f"{k}={v}" for k, v in data.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Repo Recall risk policy gate")
    parser.add_argument(
        "--contract",
        default="control/contract.yml",
        help="Path to machine-readable contract YAML",
    )
    parser.add_argument("--repo-root", default=".", help="Repo root (where .git lives)")
    parser.add_argument("--base", default=None, help="Git base ref (e.g., origin/main)")
    parser.add_argument("--head", default=None, help="Git head ref (e.g., HEAD)")
    parser.add_argument(
        "--out",
        default=None,
        help="Optional path to write JSON output (for debugging/artifacts)",
    )
    parser.add_argument(
        "--github-output",
        default=None,
        help="Optional path to write GitHub Actions outputs (e.g., $GITHUB_OUTPUT)",
    )

    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()
    contract_path = Path(args.contract).resolve()

    if not contract_path.exists():
        print(f"Contract not found: {contract_path}", file=sys.stderr)
        return 2

    contract = _load_contract(contract_path)
    tiers = _parse_tiers(contract)

    # Determine base/head
    base = args.base
    head = args.head

    if base is None:
        # GitHub PRs set GITHUB_BASE_REF (branch name), but we need a ref.
        # We'll prefer origin/<branch> if present.
        base_ref = os.environ.get("GITHUB_BASE_REF") or os.environ.get("BASE_REF")
        if base_ref:
            base = f"origin/{base_ref}"
        else:
            base = "origin/main"

    if head is None:
        head = os.environ.get("GITHUB_SHA") or "HEAD"

    # Fetch origin refs if running in CI with shallow clones (best-effort)
    try:
        _run(["git", "fetch", "--no-tags", "--prune", "--depth=200", "origin"], cwd=repo_root)
    except Exception:
        # Ignore if fetch fails (e.g., already have full history)
        pass

    try:
        changed_files = _git_changed_files(base=base, head=head, repo_root=repo_root)
    except Exception as e:
        print(f"Failed to compute changed files: {e}", file=sys.stderr)
        return 3

    tier = _tier_for_files(tiers, changed_files)
    violations = _enforce_docs_drift(contract, changed_files)

    result: dict[str, Any] = {
        "base": base,
        "head": head,
        "changed_files": changed_files,
        "risk_tier": tier.name,
        "required_checks": tier.required_checks,
        "violations": violations,
    }

    print(json.dumps(result, indent=2))

    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    if args.github_output:
        _write_github_output(
            Path(args.github_output),
            {
                "risk_tier": tier.name,
                "required_checks_json": json.dumps(tier.required_checks),
                "violations_json": json.dumps(violations),
            },
        )

    if violations:
        print("\nPolicy gate violations:", file=sys.stderr)
        for v in violations:
            print(f"- {v}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
