from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class RepoMeta(BaseModel):
    id: str
    name: Optional[str] = None
    source: Optional[str] = None
    source_ref: Optional[str] = None
    default_branch: Optional[str] = None
    indexed_commit_sha: Optional[str] = None
    last_commit_at: Optional[str] = None
    indexed_at: Optional[str] = None
    languages: Optional[dict[str, int]] = None
    summary: Optional[str] = None


class EvidenceChunk(BaseModel):
    chunk_id: str
    file_path: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    content_type: str
    score: float
    vector_score: Optional[float] = None
    lexical_score: Optional[float] = None
    text: str


class RepoCandidate(BaseModel):
    repo: RepoMeta
    score: float
    evidence: list[EvidenceChunk] = Field(default_factory=list)


class SearchDebug(BaseModel):
    vector_hits: int
    lexical_hits: int
    used_embeddings: bool


class SearchResponse(BaseModel):
    query: str
    results: list[RepoCandidate]
    debug: Optional[SearchDebug] = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "SearchResponse":
        # Be tolerant to extra fields.
        return cls.model_validate(payload)


class CatalogBranchMeta(BaseModel):
    id: str
    name: str
    head_sha: Optional[str] = None
    is_default: bool = False
    protected: bool = False
    is_generated: bool = False
    last_commit_at: Optional[str] = None
    last_synced_at: Optional[str] = None
    score: float
    reason_codes: list[str] = Field(default_factory=list)


class CatalogRepoMeta(BaseModel):
    id: str
    github_repo_id: Optional[int] = None
    owner: Optional[str] = None
    name: Optional[str] = None
    full_name: Optional[str] = None
    private: bool = True
    archived: bool = False
    disabled: bool = False
    default_branch: Optional[str] = None
    pushed_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_synced_at: Optional[str] = None
    actor_permission: Optional[str] = None
    freshness: Optional[str] = None


class CatalogSuggestion(BaseModel):
    repo: CatalogRepoMeta
    score: float
    reason_codes: list[str] = Field(default_factory=list)
    branches: list[CatalogBranchMeta] = Field(default_factory=list)


class CatalogDebug(BaseModel):
    repos_considered: int
    branches_considered: int


class CatalogSuggestResponse(BaseModel):
    actor_id: str
    query: Optional[str] = None
    results: list[CatalogSuggestion] = Field(default_factory=list)
    auth_required: bool = False
    connect_url: Optional[str] = None
    debug: Optional[CatalogDebug] = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "CatalogSuggestResponse":
        return cls.model_validate(payload)
