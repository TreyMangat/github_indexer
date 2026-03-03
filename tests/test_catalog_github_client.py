from __future__ import annotations

from typing import Any

import httpx

from repo_recall.catalog.github_client import GitHubClient


def test_list_user_repositories_handles_pagination(monkeypatch) -> None:
    client = GitHubClient(base_url="https://api.github.com", token="tkn")

    def fake_request_json(
        self: GitHubClient,
        *,
        method: str,
        path_or_url: str,
        params: dict[str, Any] | None = None,
        etag: str | None = None,
    ) -> tuple[Any, httpx.Headers, int]:
        if path_or_url.endswith("/user/repos"):
            return (
                [{"id": 1}, {"id": 2}],
                httpx.Headers(
                    {
                        "ETag": '"abc"',
                        "Link": '<https://api.github.com/user/repos?page=2>; rel="next"',
                    }
                ),
                200,
            )
        if "page=2" in path_or_url:
            return ([{"id": 3}], httpx.Headers({}), 200)
        raise AssertionError(f"Unexpected URL: {path_or_url}")

    monkeypatch.setattr(GitHubClient, "_request_json", fake_request_json)
    out = client.list_user_repositories(org=None, per_page=100, etag=None)
    assert [r["id"] for r in out.items] == [1, 2, 3]
    assert out.etag == '"abc"'
    assert out.not_modified is False


def test_list_user_repositories_not_modified(monkeypatch) -> None:
    client = GitHubClient(base_url="https://api.github.com", token="tkn")

    def fake_request_json(
        self: GitHubClient,
        *,
        method: str,
        path_or_url: str,
        params: dict[str, Any] | None = None,
        etag: str | None = None,
    ) -> tuple[Any, httpx.Headers, int]:
        return (None, httpx.Headers({}), 304)

    monkeypatch.setattr(GitHubClient, "_request_json", fake_request_json)
    out = client.list_user_repositories(org=None, per_page=100, etag='"abc"')
    assert out.items == []
    assert out.not_modified is True


def test_request_json_retries_on_5xx(monkeypatch) -> None:
    attempts = {"count": 0}
    sleeps: list[float] = []

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def request(
            self,
            method: str,
            url: str,
            params: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None,
        ) -> httpx.Response:
            attempts["count"] += 1
            req = httpx.Request(method, url)
            if attempts["count"] < 3:
                return httpx.Response(503, request=req, text="temporarily unavailable")
            return httpx.Response(200, request=req, json=[{"ok": True}])

    monkeypatch.setattr(httpx, "Client", FakeClient)
    client = GitHubClient(
        base_url="https://api.github.com",
        token="tkn",
        max_retries=4,
        backoff_base_s=0.1,
        sleep_fn=sleeps.append,
    )

    payload, _, status = client._request_json(method="GET", path_or_url="/user/repos")
    assert status == 200
    assert isinstance(payload, list)
    assert attempts["count"] == 3
    assert sleeps == [0.1, 0.2]
