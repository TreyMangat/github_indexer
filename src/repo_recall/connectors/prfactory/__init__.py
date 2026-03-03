"""PRFactory connectors.

PRFactory uses adapter-based integrations. This package provides a small adapter
and client for talking to a running Repo Recall service over HTTP (or a mock
adapter for tests).
"""

from .adapter import RepoRecallAdapter
from .http_adapter import RepoRecallHttpAdapter
from .mock_adapter import RepoRecallMockAdapter
from .types import (
    CatalogBranchMeta,
    CatalogRepoMeta,
    CatalogSuggestion,
    CatalogSuggestResponse,
    EvidenceChunk,
    RepoCandidate,
    RepoMeta,
    SearchResponse,
)

__all__ = [
    "RepoRecallAdapter",
    "RepoRecallHttpAdapter",
    "RepoRecallMockAdapter",
    "RepoMeta",
    "RepoCandidate",
    "EvidenceChunk",
    "SearchResponse",
    "CatalogRepoMeta",
    "CatalogBranchMeta",
    "CatalogSuggestion",
    "CatalogSuggestResponse",
]
