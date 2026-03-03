from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import UUID


@dataclass(frozen=True)
class GitHubRepositoryRecord:
    github_repo_id: int
    owner: str
    name: str
    full_name: str
    private: bool
    archived: bool
    disabled: bool
    default_branch: Optional[str]
    pushed_at: Optional[datetime]
    updated_at: Optional[datetime]
    source_token_owner: Optional[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GitHubBranchRecord:
    repo_id: UUID
    name: str
    head_sha: Optional[str]
    is_default: bool
    protected: bool
    last_commit_at: Optional[datetime]
    is_generated: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActorRepoAccessRecord:
    actor_id: str
    repo_id: UUID
    permission: str
    last_seen_at: datetime
