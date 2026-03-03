from __future__ import annotations

from dataclasses import dataclass

from .adapter import RepoRecallAdapter
from .types import CatalogSuggestResponse, SearchResponse


@dataclass(frozen=True)
class RepoRecallMockAdapter(RepoRecallAdapter):
    """Deterministic adapter for local dev / tests."""

    response: SearchResponse
    catalog_response: CatalogSuggestResponse | None = None

    def search(self, query: str, *, top_k_repos: int = 5, top_k_chunks: int = 3) -> SearchResponse:
        # Return the same canned response, but echo the query for realism.
        return self.response.model_copy(update={"query": query})

    def suggest_repos_and_branches(
        self,
        *,
        actor_id: str,
        query: str = "",
        org: str | None = None,
        top_k_repos: int = 5,
        top_k_branches_per_repo: int = 5,
    ) -> CatalogSuggestResponse:
        if self.catalog_response is None:
            return CatalogSuggestResponse(
                actor_id=actor_id,
                query=query,
                results=[],
                auth_required=False,
                connect_url=None,
                debug=None,
            )
        return self.catalog_response.model_copy(update={"actor_id": actor_id, "query": query})
