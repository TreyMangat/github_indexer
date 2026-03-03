from __future__ import annotations

from typing import Any

import httpx

from repo_recall.connectors.prfactory import RepoRecallHttpAdapter


def test_http_adapter_catalog_suggest_calls_expected_endpoint(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        def __init__(self) -> None:
            self.status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "actor_id": "U123",
                "query": "api",
                "results": [],
                "auth_required": False,
            }

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def post(
            self,
            url: str,
            *,
            json: dict[str, Any],
            headers: dict[str, str],
        ) -> FakeResponse:
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    adapter = RepoRecallHttpAdapter(base_url="http://repo-recall:8080", token="abc")
    out = adapter.suggest_repos_and_branches(actor_id="U123", query="api", top_k_repos=3)

    assert captured["url"] == "http://repo-recall:8080/api/indexer/catalog/suggest"
    assert captured["json"]["actor_id"] == "U123"
    assert captured["json"]["top_k_repos"] == 3
    assert captured["headers"]["X-FF-Token"] == "abc"
    assert out.actor_id == "U123"
