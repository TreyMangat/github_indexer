from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional, cast
from urllib.parse import parse_qs, urlparse

import httpx


class GitHubClientError(RuntimeError):
    """Raised when GitHub API requests fail."""


def parse_github_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # GitHub timestamps use UTC with trailing "Z".
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


@dataclass(frozen=True)
class PaginatedResult:
    items: list[dict[str, Any]]
    etag: Optional[str]
    not_modified: bool


class GitHubClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_s: float = 20.0,
        max_retries: int = 4,
        backoff_base_s: float = 0.5,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_s = timeout_s
        self._max_retries = max(0, max_retries)
        self._backoff_base_s = max(0.01, backoff_base_s)
        self._sleep_fn = sleep_fn

    def _request_json(
        self,
        *,
        method: str,
        path_or_url: str,
        params: Optional[dict[str, Any]] = None,
        etag: Optional[str] = None,
    ) -> tuple[Optional[Any], httpx.Headers, int]:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if etag:
            headers["If-None-Match"] = etag

        url = path_or_url if path_or_url.startswith("http") else f"{self._base_url}{path_or_url}"
        last_error: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):
            try:
                with httpx.Client(timeout=self._timeout_s) as client:
                    resp = client.request(method, url, params=params, headers=headers)
            except httpx.HTTPError as e:
                last_error = e
                if attempt >= self._max_retries:
                    raise GitHubClientError(f"GitHub request failed: {e}") from e
                self._sleep_fn(self._backoff_base_s * (2**attempt))
                continue

            if resp.status_code == 304:
                return None, resp.headers, resp.status_code

            if resp.status_code in {429, 500, 502, 503, 504} and attempt < self._max_retries:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    self._sleep_fn(float(retry_after))
                else:
                    self._sleep_fn(self._backoff_base_s * (2**attempt))
                continue

            if resp.status_code >= 400:
                detail = resp.text[:800]
                raise GitHubClientError(
                    f"GitHub API {resp.status_code} for {url}: {detail}"
                )

            payload = resp.json()
            return payload, resp.headers, resp.status_code

        if last_error:
            raise GitHubClientError(f"GitHub request failed: {last_error}") from last_error
        raise GitHubClientError("GitHub request failed with unknown error")

    @staticmethod
    def _next_link(headers: httpx.Headers) -> Optional[str]:
        raw = headers.get("Link") or headers.get("link")
        if not raw:
            return None
        for part in raw.split(","):
            section = part.strip()
            if 'rel="next"' not in section:
                continue
            if "<" not in section or ">" not in section:
                continue
            link = section.split("<", 1)[1].split(">", 1)[0].strip()
            return str(link)
        return None

    def _list_paginated(
        self,
        *,
        path: str,
        params: dict[str, Any],
        etag: Optional[str],
    ) -> PaginatedResult:
        first_payload, first_headers, first_status = self._request_json(
            method="GET",
            path_or_url=path,
            params=params,
            etag=etag,
        )
        if first_status == 304:
            return PaginatedResult(items=[], etag=etag, not_modified=True)
        if not isinstance(first_payload, list):
            raise GitHubClientError(f"Expected list payload for {path}")

        items: list[dict[str, Any]] = [x for x in first_payload if isinstance(x, dict)]
        response_etag = first_headers.get("ETag") or first_headers.get("etag") or etag
        next_link = self._next_link(first_headers)

        while next_link:
            parsed = urlparse(next_link)
            query_params = (
                {
                    k: v[0]
                    for k, v in parse_qs(parsed.query, keep_blank_values=False).items()
                    if v
                }
                if not parsed.netloc
                else None
            )
            page_payload, page_headers, _ = self._request_json(
                method="GET",
                path_or_url=next_link,
                params=query_params,
                etag=None,
            )
            if not isinstance(page_payload, list):
                raise GitHubClientError(f"Expected list payload for paginated URL: {next_link}")
            items.extend([x for x in page_payload if isinstance(x, dict)])
            next_link = self._next_link(page_headers)

        return PaginatedResult(items=items, etag=response_etag, not_modified=False)

    def list_user_repositories(
        self,
        *,
        org: Optional[str],
        per_page: int = 100,
        etag: Optional[str] = None,
    ) -> PaginatedResult:
        per_page = max(1, min(int(per_page), 100))
        result = self._list_paginated(
            path="/user/repos",
            params={
                "visibility": "all",
                "affiliation": "owner,collaborator,organization_member",
                "sort": "updated",
                "per_page": per_page,
            },
            etag=etag,
        )
        if org:
            org_l = org.lower()
            filtered = []
            for item in result.items:
                owner_obj = item.get("owner")
                if not isinstance(owner_obj, dict):
                    continue
                login = str(owner_obj.get("login") or "").lower()
                if login == org_l:
                    filtered.append(item)
            return PaginatedResult(items=filtered, etag=result.etag, not_modified=result.not_modified)
        return result

    def get_repository(self, *, full_name: str) -> dict[str, Any]:
        payload, _, _ = self._request_json(
            method="GET",
            path_or_url=f"/repos/{full_name}",
            params=None,
            etag=None,
        )
        if not isinstance(payload, dict):
            raise GitHubClientError(f"Expected object payload for repo {full_name}")
        return payload

    def list_repository_branches(
        self,
        *,
        full_name: str,
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        per_page = max(1, min(int(per_page), 100))
        result = self._list_paginated(
            path=f"/repos/{full_name}/branches",
            params={"per_page": per_page},
            etag=None,
        )
        return result.items

    def get_commit_datetime(
        self,
        *,
        full_name: str,
        sha: str,
    ) -> Optional[datetime]:
        payload, _, _ = self._request_json(
            method="GET",
            path_or_url=f"/repos/{full_name}/commits/{sha}",
            params=None,
            etag=None,
        )
        if not isinstance(payload, dict):
            return None
        payload_obj = cast(dict[str, Any], payload)
        commit = payload_obj.get("commit")
        if not isinstance(commit, dict):
            return None
        committer = commit.get("committer")
        if isinstance(committer, dict):
            dt = parse_github_datetime(str(committer.get("date") or ""))
            if dt:
                return dt
        author = commit.get("author")
        if isinstance(author, dict):
            return parse_github_datetime(str(author.get("date") or ""))
        return None
