from __future__ import annotations

from datetime import datetime, timedelta, timezone

from repo_recall.catalog.scoring import (
    freshness_state,
    is_generated_branch,
    rank_repositories_and_branches,
)


def test_generated_branch_detection() -> None:
    assert is_generated_branch("prfactory/auto-123")
    assert is_generated_branch("dependabot/pip/urllib3")
    assert not is_generated_branch("feature/user-profile")


def test_freshness_state_buckets() -> None:
    now = datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc)
    assert freshness_state(now, now=now) == "fresh"
    assert freshness_state(now - timedelta(hours=4), now=now) == "stale"
    assert freshness_state(now - timedelta(days=2), now=now) == "expired"
    assert freshness_state(None, now=now) == "unknown"


def test_rank_repositories_and_branches_prefers_default_and_non_generated() -> None:
    now = datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc)
    repos = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "api-service",
            "full_name": "org/api-service",
            "owner": "org",
            "private": True,
            "archived": False,
            "disabled": False,
            "default_branch": "main",
            "updated_at": now - timedelta(days=1),
            "pushed_at": now - timedelta(days=1),
            "last_synced_at": now - timedelta(minutes=5),
            "actor_last_seen_at": now - timedelta(hours=2),
            "actor_permission": "write",
            "github_repo_id": 1,
        }
    ]
    branches = {
        "11111111-1111-1111-1111-111111111111": [
            {
                "id": "b1",
                "name": "main",
                "is_default": True,
                "protected": True,
                "is_generated": False,
                "last_commit_at": now - timedelta(days=2),
                "last_synced_at": now - timedelta(minutes=5),
                "head_sha": "abc",
            },
            {
                "id": "b2",
                "name": "prfactory/auto-7",
                "is_default": False,
                "protected": False,
                "is_generated": True,
                "last_commit_at": now - timedelta(minutes=10),
                "last_synced_at": now - timedelta(minutes=5),
                "head_sha": "def",
            },
            {
                "id": "b3",
                "name": "feature/login",
                "is_default": False,
                "protected": False,
                "is_generated": False,
                "last_commit_at": now - timedelta(hours=1),
                "last_synced_at": now - timedelta(minutes=5),
                "head_sha": "ghi",
            },
        ]
    }

    ranked = rank_repositories_and_branches(
        repos,
        branches,
        query="login",
        top_k_repos=5,
        top_k_branches_per_repo=2,
        now=now,
    )
    assert len(ranked) == 1
    branch_names = [b["name"] for b in ranked[0]["branches"]]
    # default branch is always present in output
    assert "main" in branch_names
    # generated branch gets penalized and should not beat a relevant feature branch here
    assert "feature/login" in branch_names
    assert "prfactory/auto-7" not in branch_names
