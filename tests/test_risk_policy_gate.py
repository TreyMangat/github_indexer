import json
import subprocess
from pathlib import Path


def _run(cmd, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def _init_git_repo(repo: Path) -> None:
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)


def test_risk_policy_gate_selects_medium(tmp_path: Path):
    repo = tmp_path / "r"
    repo.mkdir()
    _init_git_repo(repo)

    # contract + docs
    (repo / "control").mkdir()
    (repo / "docs").mkdir()
    (repo / "control" / "contract.yml").write_text(
        """version: 1
risk_tiers:
  - name: low
    priority: 10
    match: ["docs/**", "**/*.md"]
    required_checks: ["lint"]
  - name: medium
    priority: 20
    match: ["src/**", "**/*.py"]
    required_checks: ["lint", "unit-tests"]
docs_drift_rules: []
""",
        encoding="utf-8",
    )
    (repo / "docs" / "POLICY.md").write_text("policy", encoding="utf-8")
    (repo / "docs" / "x.md").write_text("hello", encoding="utf-8")

    _run(["git", "add", "."], cwd=repo)
    _run(["git", "commit", "-m", "init"], cwd=repo)

    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("def foo():\n  return 1\n", encoding="utf-8")
    _run(["git", "add", "."], cwd=repo)
    _run(["git", "commit", "-m", "add code"], cwd=repo)

    proc = _run(
        [
            "python",
            str(Path(__file__).resolve().parents[1] / "scripts" / "risk_policy_gate.py"),
            "--repo-root",
            str(repo),
            "--contract",
            str(repo / "control" / "contract.yml"),
            "--base",
            "HEAD~1",
            "--head",
            "HEAD",
        ],
        cwd=repo,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["risk_tier"] == "medium"


def test_risk_policy_gate_docs_drift_violation(tmp_path: Path):
    repo = tmp_path / "r"
    repo.mkdir()
    _init_git_repo(repo)

    (repo / "control").mkdir()
    (repo / "docs").mkdir()
    (repo / "control" / "contract.yml").write_text(
        """version: 1
risk_tiers:
  - name: low
    priority: 10
    match: ["**/*"]
    required_checks: ["lint"]
docs_drift_rules:
  - name: contract_updates_require_policy_doc
    when_changed: ["control/contract.yml"]
    require_updated: ["docs/POLICY.md"]
""",
        encoding="utf-8",
    )
    (repo / "docs" / "POLICY.md").write_text("policy v1", encoding="utf-8")
    _run(["git", "add", "."], cwd=repo)
    _run(["git", "commit", "-m", "init"], cwd=repo)

    # change contract without updating docs/POLICY.md
    (repo / "control" / "contract.yml").write_text(
        """version: 1
risk_tiers:
  - name: low
    priority: 10
    match: ["**/*"]
    required_checks: ["lint", "unit-tests"]
docs_drift_rules:
  - name: contract_updates_require_policy_doc
    when_changed: ["control/contract.yml"]
    require_updated: ["docs/POLICY.md"]
""",
        encoding="utf-8",
    )
    _run(["git", "add", "."], cwd=repo)
    _run(["git", "commit", "-m", "change contract"], cwd=repo)

    proc = _run(
        [
            "python",
            str(Path(__file__).resolve().parents[1] / "scripts" / "risk_policy_gate.py"),
            "--repo-root",
            str(repo),
            "--contract",
            str(repo / "control" / "contract.yml"),
            "--base",
            "HEAD~1",
            "--head",
            "HEAD",
        ],
        cwd=repo,
    )
    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["violations"], "expected violations"
