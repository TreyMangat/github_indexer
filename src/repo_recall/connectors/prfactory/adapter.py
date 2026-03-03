from __future__ import annotations

from typing import Protocol

from .types import CatalogSuggestResponse, SearchResponse


class RepoRecallAdapter(Protocol):
    """Adapter interface PRFactory can depend on.

    Keep it small: one method to map an intent/prompt to ranked repo candidates.
    """

    def search(
        self, query: str, *, top_k_repos: int = 5, top_k_chunks: int = 3
    ) -> SearchResponse: ...

    def suggest_repos_and_branches(
        self,
        *,
        actor_id: str,
        query: str = "",
        org: str | None = None,
        top_k_repos: int = 5,
        top_k_branches_per_repo: int = 5,
    ) -> CatalogSuggestResponse: ...
