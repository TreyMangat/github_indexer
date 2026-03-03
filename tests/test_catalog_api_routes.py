from __future__ import annotations

import os
import uuid
from typing import Any

os.environ.setdefault("DATABASE_URL", "postgresql://example:example@localhost:5432/example")

from repo_recall.api import app as api_app


class _FakeTokenStore:
    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self.set_calls: list[tuple[str, str]] = []

    def set(self, *, actor_id: str, token: str, ttl_seconds: int = 3600) -> None:
        self.set_calls.append((actor_id, token))
        self.token = token

    def get(self, *, actor_id: str) -> str | None:
        return self.token


class _FakeService:
    def __init__(self, suggest_payload: dict[str, Any]) -> None:
        self._suggest_payload = suggest_payload
        self.seed_calls: list[dict[str, Any]] = []

    def suggest(self, **kwargs: Any) -> dict[str, Any]:
        return dict(self._suggest_payload)

    def connect_url(self, *, actor_id: str) -> str:
        return f"https://connect.example.com/github?actor_id={actor_id}"

    def seed_demo_data(self, **kwargs: Any) -> dict[str, Any]:
        self.seed_calls.append(kwargs)
        return {"repos_seeded": 3, "branches_seeded": 8}


class _FakeRunner:
    def __init__(self, *, suggest_payload: dict[str, Any], token: str | None = None) -> None:
        self.token_store = _FakeTokenStore(token=token)
        self.service = _FakeService(suggest_payload=suggest_payload)
        self.sync_calls: list[dict[str, Any]] = []

    def submit_sync(self, **kwargs: Any) -> uuid.UUID:
        self.sync_calls.append(kwargs)
        return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def test_catalog_sync_returns_auth_required_without_token(monkeypatch) -> None:
    runner = _FakeRunner(suggest_payload={"results": []}, token=None)
    monkeypatch.setattr(api_app, "_catalog_runner_or_404", lambda: runner)

    out = api_app.catalog_sync(api_app.CatalogSyncRequest(actor_id="U1", scope="incremental"))
    assert out["status"] == "auth_required"
    assert out["auth_required"] is True
    assert "connect_url" in out


def test_catalog_suggest_bootstraps_sync_when_token_provided(monkeypatch) -> None:
    runner = _FakeRunner(
        suggest_payload={
            "actor_id": "U1",
            "query": "api",
            "results": [],
            "auth_required": True,
            "connect_url": "https://connect.example.com",
            "debug": {"repos_considered": 0, "branches_considered": 0},
        },
        token=None,
    )
    monkeypatch.setattr(api_app, "_catalog_runner_or_404", lambda: runner)

    req = api_app.CatalogSuggestRequest(actor_id="U1", query="api", github_token="tok")
    out = api_app.catalog_suggest(req=req, conn=object())
    assert out["auth_required"] is False
    assert out["connect_url"] is None
    assert out["debug"]["sync_queued"] is True
    assert out["debug"]["sync_run_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_catalog_dev_set_token_endpoint(monkeypatch) -> None:
    runner = _FakeRunner(suggest_payload={"results": []}, token=None)
    monkeypatch.setattr(api_app, "_catalog_runner_or_404", lambda: runner)
    monkeypatch.setattr(api_app.settings, "enable_catalog_dev_endpoints", True)

    out = api_app.catalog_set_actor_token(
        api_app.CatalogSetTokenRequest(actor_id="U1", github_token="gho_xxx", ttl_seconds=600)
    )
    assert out["status"] == "stored"
    assert runner.token_store.set_calls[0][0] == "U1"


def test_catalog_dev_seed_endpoint(monkeypatch) -> None:
    runner = _FakeRunner(suggest_payload={"results": []}, token=None)
    monkeypatch.setattr(api_app, "_catalog_runner_or_404", lambda: runner)
    monkeypatch.setattr(api_app.settings, "enable_catalog_dev_endpoints", True)

    out = api_app.catalog_seed_demo(
        req=api_app.CatalogSeedDemoRequest(actor_id="U1", org="demo-org"),
        conn=object(),
    )
    assert out["status"] == "seeded"
    assert out["seed"]["repos_seeded"] == 3
