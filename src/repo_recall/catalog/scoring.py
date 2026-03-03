from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

GENERATED_BRANCH_PREFIXES = (
    "prfactory/",
    "dependabot/",
    "renovate/",
    "release-please/",
    "gh-readonly-queue/",
)


def is_generated_branch(name: str) -> bool:
    n = name.strip().lower()
    if not n:
        return False
    return any(n.startswith(prefix) for prefix in GENERATED_BRANCH_PREFIXES)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def freshness_state(
    last_synced_at: Optional[datetime],
    *,
    now: Optional[datetime] = None,
) -> str:
    ts = _as_utc(last_synced_at)
    if ts is None:
        return "unknown"
    now_utc = _as_utc(now) or datetime.now(timezone.utc)
    age_s = max(0.0, (now_utc - ts).total_seconds())
    if age_s <= 3600:
        return "fresh"
    if age_s <= 86400:
        return "stale"
    return "expired"


def _query_parts(query: Optional[str]) -> tuple[str, str]:
    q = (query or "").strip().lower()
    return q, q.replace("_", "-")


def _repo_score(repo: dict[str, Any], *, query: Optional[str], now_utc: datetime) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    q, q2 = _query_parts(query)

    name = str(repo.get("name") or "").lower()
    full_name = str(repo.get("full_name") or "").lower()
    if q:
        if q == full_name or q == name:
            score += 2.0
            reasons.append("name_exact")
        elif full_name.startswith(q) or name.startswith(q):
            score += 1.2
            reasons.append("name_prefix")
        elif q in full_name or q2 in full_name or q in name:
            score += 0.8
            reasons.append("name_match")

    pushed_at = _as_utc(repo.get("pushed_at"))
    if pushed_at:
        days = (now_utc - pushed_at).total_seconds() / 86400.0
        if days <= 7:
            score += 0.7
            reasons.append("recently_updated")
        elif days <= 30:
            score += 0.3

    actor_seen = _as_utc(repo.get("actor_last_seen_at"))
    if actor_seen:
        days = (now_utc - actor_seen).total_seconds() / 86400.0
        if days <= 7:
            score += 0.4
            reasons.append("recently_used")

    if bool(repo.get("archived")):
        score -= 1.2
        reasons.append("archived_penalty")
    if bool(repo.get("disabled")):
        score -= 1.0
        reasons.append("disabled_penalty")

    return score, reasons


def _branch_score(
    branch: dict[str, Any],
    *,
    query: Optional[str],
    now_utc: datetime,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    q, q2 = _query_parts(query)
    name = str(branch.get("name") or "")
    name_l = name.lower()

    if bool(branch.get("is_default")):
        score += 1.0
        reasons.append("default_branch")
    if q:
        if name_l == q:
            score += 1.0
            reasons.append("name_match")
        elif name_l.startswith(q) or q in name_l or q2 in name_l:
            score += 0.4
            reasons.append("name_match")

    last_commit_at = _as_utc(branch.get("last_commit_at"))
    if last_commit_at:
        days = (now_utc - last_commit_at).total_seconds() / 86400.0
        if days <= 7:
            score += 0.6
            reasons.append("recently_updated")
        elif days <= 30:
            score += 0.25

    if bool(branch.get("is_generated")):
        score -= 0.9
        reasons.append("generated_penalty")

    if bool(branch.get("protected")):
        score += 0.05

    return score, reasons


def rank_repositories_and_branches(
    repos: list[dict[str, Any]],
    branches_by_repo_id: dict[str, list[dict[str, Any]]],
    *,
    query: Optional[str],
    top_k_repos: int,
    top_k_branches_per_repo: int,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    now_utc = _as_utc(now) or datetime.now(timezone.utc)
    repo_rows: list[tuple[float, list[str], dict[str, Any]]] = []

    for repo in repos:
        s, reasons = _repo_score(repo, query=query, now_utc=now_utc)
        repo_rows.append((s, reasons, repo))

    repo_rows.sort(
        key=lambda x: (
            x[0],
            _as_utc(x[2].get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc),
            str(x[2].get("full_name") or ""),
        ),
        reverse=True,
    )
    repo_rows = repo_rows[: max(1, top_k_repos)]

    out: list[dict[str, Any]] = []
    for repo_score, repo_reasons, repo in repo_rows:
        repo_id = str(repo.get("id"))
        branches = branches_by_repo_id.get(repo_id, [])
        branch_rows: list[tuple[float, list[str], dict[str, Any]]] = []
        for b in branches:
            bs, breasons = _branch_score(b, query=query, now_utc=now_utc)
            branch_rows.append((bs, breasons, b))
        branch_rows.sort(
            key=lambda x: (
                x[0],
                _as_utc(x[2].get("last_commit_at"))
                or datetime.min.replace(tzinfo=timezone.utc),
                str(x[2].get("name") or ""),
            ),
            reverse=True,
        )

        top_n = max(1, top_k_branches_per_repo)
        chosen = branch_rows[:top_n]
        if branches:
            default_branch = next((r for r in branch_rows if bool(r[2].get("is_default"))), None)
            if default_branch and default_branch not in chosen:
                if len(chosen) < top_n:
                    chosen.append(default_branch)
                else:
                    chosen[-1] = default_branch

        out.append(
            {
                "repo": {
                    "id": repo_id,
                    "github_repo_id": repo.get("github_repo_id"),
                    "owner": repo.get("owner"),
                    "name": repo.get("name"),
                    "full_name": repo.get("full_name"),
                    "private": bool(repo.get("private")),
                    "archived": bool(repo.get("archived")),
                    "disabled": bool(repo.get("disabled")),
                    "default_branch": repo.get("default_branch"),
                    "pushed_at": str(repo.get("pushed_at")) if repo.get("pushed_at") else None,
                    "updated_at": str(repo.get("updated_at")) if repo.get("updated_at") else None,
                    "last_synced_at": str(repo.get("last_synced_at"))
                    if repo.get("last_synced_at")
                    else None,
                    "actor_permission": repo.get("actor_permission"),
                    "freshness": freshness_state(repo.get("last_synced_at"), now=now_utc),
                },
                "score": repo_score,
                "reason_codes": repo_reasons,
                "branches": [
                    {
                        "id": str(b.get("id")),
                        "name": b.get("name"),
                        "head_sha": b.get("head_sha"),
                        "is_default": bool(b.get("is_default")),
                        "protected": bool(b.get("protected")),
                        "is_generated": bool(b.get("is_generated")),
                        "last_commit_at": str(b.get("last_commit_at"))
                        if b.get("last_commit_at")
                        else None,
                        "last_synced_at": str(b.get("last_synced_at"))
                        if b.get("last_synced_at")
                        else None,
                        "score": s,
                        "reason_codes": reasons,
                    }
                    for s, reasons, b in chosen
                ],
            }
        )
    return out
