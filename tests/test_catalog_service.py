from __future__ import annotations

from repo_recall.catalog.service import CatalogService
from repo_recall.config import Settings


def test_suggest_returns_auth_required_when_no_cached_repos(monkeypatch) -> None:
    def fake_list_actor_repositories(*args, **kwargs):  # type: ignore[no-untyped-def]
        return []

    monkeypatch.setattr("repo_recall.catalog.service.list_actor_repositories", fake_list_actor_repositories)

    settings = Settings.model_validate(
        {
            "DATABASE_URL": "postgresql://example:example@localhost:5432/example",
            "GITHUB_CONNECT_URL_TEMPLATE": "https://connect.example.com/github?actor_id={actor_id}",
        }
    )
    svc = CatalogService(settings)
    out = svc.suggest(
        conn=object(),
        actor_id="U123",
        query="repo",
        org=None,
        top_k_repos=5,
        top_k_branches_per_repo=3,
    )
    assert out["auth_required"] is True
    assert out["connect_url"] == "https://connect.example.com/github?actor_id=U123"
