from __future__ import annotations

from typing import Any

import httpx

from repo_recall.catalog.token_provider import CatalogTokenProvider
from repo_recall.config import Settings


def _settings() -> Settings:
    return Settings.model_validate({"DATABASE_URL": "postgresql://x:x@localhost:5432/x"})


def test_token_provider_uses_memory_first() -> None:
    p = CatalogTokenProvider(_settings())
    p.set(actor_id="U1", token="tok", ttl_seconds=600)
    out = p.get(actor_id="U1")
    assert out.token == "tok"
    assert out.source == "memory"


def test_token_provider_uses_broker_when_cache_miss(monkeypatch) -> None:
    settings = Settings.model_validate(
        {
            "DATABASE_URL": "postgresql://x:x@localhost:5432/x",
            "GITHUB_TOKEN_BROKER_URL": "https://broker.example.com/token",
            "GITHUB_TOKEN_BROKER_AUTH_TOKEN": "svc-token",
        }
    )

    class FakeResp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"token": "gho_from_broker", "expires_in_seconds": 1200}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, str]) -> FakeResp:
            assert url == "https://broker.example.com/token"
            assert headers["Authorization"] == "Bearer svc-token"
            assert json["actor_id"] == "U1"
            return FakeResp()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    p = CatalogTokenProvider(settings)
    out = p.get(actor_id="U1")
    assert out.token == "gho_from_broker"
    assert out.source == "broker"
    out2 = p.get(actor_id="U1")
    assert out2.source == "memory"
