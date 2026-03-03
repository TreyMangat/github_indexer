from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import httpx

from .adapter import RepoRecallAdapter
from .types import CatalogSuggestResponse, SearchResponse


@dataclass(frozen=True)
class RepoRecallHttpAdapter(RepoRecallAdapter):
    """HTTP adapter for PRFactory -> Repo Recall."""

    base_url: str
    token: Optional[str] = None
    timeout_s: float = 15.0

    @classmethod
    def from_env(
        cls,
        *,
        base_url_env: str = "INDEXER_BASE_URL",
        token_env: str = "INDEXER_AUTH_TOKEN",
    ) -> "RepoRecallHttpAdapter":
        base_url = os.environ.get(base_url_env, "").strip()
        if not base_url:
            raise RuntimeError(f"Missing {base_url_env} env var")
        token = os.environ.get(token_env)
        token = token.strip() if token else None
        return cls(base_url=base_url.rstrip("/"), token=token)

    def search(self, query: str, *, top_k_repos: int = 5, top_k_chunks: int = 3) -> SearchResponse:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            # Repo Recall accepts either header; sending both makes integration easy.
            headers["Authorization"] = f"Bearer {self.token}"
            headers["X-FF-Token"] = self.token

        payload = {"query": query, "top_k_repos": top_k_repos, "top_k_chunks": top_k_chunks}

        with httpx.Client(timeout=self.timeout_s) as client:
            resp = client.post(f"{self.base_url}/search", json=payload, headers=headers)
            resp.raise_for_status()
            return SearchResponse.from_api(resp.json())

    def suggest_repos_and_branches(
        self,
        *,
        actor_id: str,
        query: str = "",
        org: Optional[str] = None,
        top_k_repos: int = 5,
        top_k_branches_per_repo: int = 5,
    ) -> CatalogSuggestResponse:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            headers["X-FF-Token"] = self.token

        payload: dict[str, object] = {
            "actor_id": actor_id,
            "query": query,
            "top_k_repos": top_k_repos,
            "top_k_branches_per_repo": top_k_branches_per_repo,
        }
        if org:
            payload["org"] = org

        with httpx.Client(timeout=self.timeout_s) as client:
            resp = client.post(f"{self.base_url}/api/indexer/catalog/suggest", json=payload, headers=headers)
            resp.raise_for_status()
            return CatalogSuggestResponse.from_api(resp.json())
