from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import psycopg

from ..config import Settings
from . import db as catalog_db
from .auth import ActorTokenStore
from .db import (
    create_webhook_delivery,
    list_actor_repositories,
    list_repo_branches_for_actor,
    prune_actor_repo_access,
    prune_repo_branches,
    update_github_index_run,
    update_webhook_delivery,
    upsert_actor_repo_access,
    upsert_github_branch,
    upsert_github_repository,
    upsert_sync_cursor,
)
from .github_client import GitHubClient, GitHubClientError, parse_github_datetime
from .models import ActorRepoAccessRecord, GitHubBranchRecord, GitHubRepositoryRecord
from .scoring import is_generated_branch, rank_repositories_and_branches

logger = logging.getLogger(__name__)

DemoBranch = tuple[str, bool, bool, datetime, bool]
DemoRepo = tuple[
    int,
    str,
    str,
    str,
    bool,
    bool,
    bool,
    str,
    datetime,
    datetime,
    list[DemoBranch],
]


def _permission_from_repo_payload(payload: dict[str, Any]) -> str:
    perms = payload.get("permissions")
    if not isinstance(perms, dict):
        return "read"
    if bool(perms.get("admin")):
        return "admin"
    if bool(perms.get("maintain")):
        return "maintain"
    if bool(perms.get("push")):
        return "write"
    if bool(perms.get("triage")):
        return "triage"
    if bool(perms.get("pull")):
        return "read"
    return "read"


def _safe_repo_name_from_full(full_name: str) -> str:
    if "/" in full_name:
        return full_name.split("/", 1)[1]
    return full_name


@dataclass(frozen=True)
class SyncResult:
    run_id: UUID
    status: str
    metrics: dict[str, Any]


class CatalogService:
    def __init__(self, settings: Settings, *, token_store: Optional[ActorTokenStore] = None) -> None:
        self.settings = settings
        self.token_store = token_store or ActorTokenStore()

    def connect_url(self, *, actor_id: str) -> str:
        tpl = self.settings.github_connect_url_template
        try:
            return tpl.format(actor_id=actor_id)
        except Exception:
            return f"/connect/github?actor_id={actor_id}"

    def _client(self, *, token: str) -> GitHubClient:
        return GitHubClient(
            base_url=self.settings.github_api_base_url,
            token=token,
            timeout_s=self.settings.catalog_request_timeout_seconds,
        )

    def _repo_record_from_payload(
        self,
        payload: dict[str, Any],
        *,
        source_token_owner: Optional[str],
    ) -> GitHubRepositoryRecord:
        owner_block = payload.get("owner")
        owner = ""
        if isinstance(owner_block, dict):
            owner = str(owner_block.get("login") or "")
        full_name = str(payload.get("full_name") or "").strip()
        repo_name = str(payload.get("name") or "").strip() or _safe_repo_name_from_full(full_name)
        if not owner and "/" in full_name:
            owner = full_name.split("/", 1)[0]

        return GitHubRepositoryRecord(
            github_repo_id=int(payload.get("id") or 0),
            owner=owner,
            name=repo_name,
            full_name=full_name,
            private=bool(payload.get("private")),
            archived=bool(payload.get("archived")),
            disabled=bool(payload.get("disabled")),
            default_branch=cast_str(payload.get("default_branch")),
            pushed_at=parse_github_datetime(cast_str(payload.get("pushed_at"))),
            updated_at=parse_github_datetime(cast_str(payload.get("updated_at"))),
            source_token_owner=source_token_owner,
            metadata={
                "html_url": cast_str(payload.get("html_url")),
                "visibility": cast_str(payload.get("visibility")),
            },
        )

    def _branch_record_from_payload(
        self,
        payload: dict[str, Any],
        *,
        repo_id: UUID,
        default_branch: Optional[str],
        last_commit_at: Optional[datetime],
    ) -> GitHubBranchRecord:
        name = cast_str(payload.get("name")) or ""
        commit = payload.get("commit")
        sha: Optional[str] = None
        if isinstance(commit, dict):
            sha = cast_str(commit.get("sha"))

        return GitHubBranchRecord(
            repo_id=repo_id,
            name=name,
            head_sha=sha,
            is_default=bool(default_branch and name == default_branch),
            protected=bool(payload.get("protected")),
            last_commit_at=last_commit_at,
            is_generated=is_generated_branch(name),
            metadata={},
        )

    def _sync_single_repo(
        self,
        *,
        conn: psycopg.Connection[Any],
        client: GitHubClient,
        actor_id: str,
        repo_payload: dict[str, Any],
        source_token_owner: Optional[str],
    ) -> tuple[UUID, int]:
        repo_rec = self._repo_record_from_payload(
            repo_payload,
            source_token_owner=source_token_owner,
        )
        repo_id = upsert_github_repository(conn, repo_rec)
        upsert_actor_repo_access(
            conn,
            ActorRepoAccessRecord(
                actor_id=actor_id,
                repo_id=repo_id,
                permission=_permission_from_repo_payload(repo_payload),
                last_seen_at=datetime.now(timezone.utc),
            ),
        )

        branches_payload = client.list_repository_branches(
            full_name=repo_rec.full_name,
            per_page=self.settings.catalog_branch_page_size,
        )
        keep_branch_names: list[str] = []
        branches_seen = 0
        for br in branches_payload:
            name = cast_str(br.get("name")) or ""
            if not name:
                continue
            commit = br.get("commit")
            sha = cast_str(commit.get("sha")) if isinstance(commit, dict) else None
            last_commit_at: Optional[datetime] = None
            if sha:
                try:
                    last_commit_at = client.get_commit_datetime(full_name=repo_rec.full_name, sha=sha)
                except GitHubClientError:
                    last_commit_at = None

            branch_rec = self._branch_record_from_payload(
                br,
                repo_id=repo_id,
                default_branch=repo_rec.default_branch,
                last_commit_at=last_commit_at,
            )
            upsert_github_branch(conn, branch_rec)
            keep_branch_names.append(branch_rec.name)
            branches_seen += 1

        prune_repo_branches(conn, repo_id=repo_id, keep_branch_names=keep_branch_names)
        return repo_id, branches_seen

    def sync_actor(
        self,
        *,
        conn: psycopg.Connection[Any],
        actor_id: str,
        scope: str,
        github_token: str,
        org: Optional[str] = None,
        source_token_owner: Optional[str] = None,
        repo_full_name: Optional[str] = None,
        run_id: UUID,
    ) -> SyncResult:
        started = datetime.now(timezone.utc)
        update_github_index_run(conn, run_id=run_id, status="running", started_at=started)

        client = self._client(token=github_token)
        keep_repo_ids: list[UUID] = []
        repos_seen = 0
        branches_seen = 0
        result_etag: Optional[str] = None
        not_modified = False

        try:
            if repo_full_name:
                repo_payload = client.get_repository(full_name=repo_full_name)
                repo_id, branches_count = self._sync_single_repo(
                    conn=conn,
                    client=client,
                    actor_id=actor_id,
                    repo_payload=repo_payload,
                    source_token_owner=source_token_owner,
                )
                keep_repo_ids.append(repo_id)
                repos_seen = 1
                branches_seen = branches_count
            else:
                cursor = catalog_db.get_sync_cursor(conn, actor_id=actor_id, scope=scope, org=org)
                etag = cast_str(cursor.get("etag")) if cursor else None
                repos_result = client.list_user_repositories(
                    org=org,
                    per_page=self.settings.catalog_repo_page_size,
                    etag=etag,
                )
                result_etag = repos_result.etag
                not_modified = repos_result.not_modified
                for payload in repos_result.items:
                    repo_id, b_count = self._sync_single_repo(
                        conn=conn,
                        client=client,
                        actor_id=actor_id,
                        repo_payload=payload,
                        source_token_owner=source_token_owner,
                    )
                    keep_repo_ids.append(repo_id)
                    repos_seen += 1
                    branches_seen += b_count
                if not not_modified:
                    prune_actor_repo_access(conn, actor_id=actor_id, keep_repo_ids=keep_repo_ids)
                upsert_sync_cursor(
                    conn,
                    actor_id=actor_id,
                    scope=scope,
                    org=org,
                    cursor={
                        "repos_seen": repos_seen,
                        "branches_seen": branches_seen,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    },
                    etag=result_etag,
                )

            finished = datetime.now(timezone.utc)
            metrics = {
                "repos_seen": repos_seen,
                "branches_seen": branches_seen,
                "not_modified": not_modified,
                "repo_full_name": repo_full_name,
            }
            update_github_index_run(
                conn,
                run_id=run_id,
                status="succeeded",
                finished_at=finished,
                error=None,
                metrics=metrics,
            )
            return SyncResult(run_id=run_id, status="succeeded", metrics=metrics)
        except Exception as e:
            finished = datetime.now(timezone.utc)
            logger.exception("Catalog sync failed actor=%s scope=%s", actor_id, scope)
            update_github_index_run(
                conn,
                run_id=run_id,
                status="failed",
                finished_at=finished,
                error=str(e),
                metrics={
                    "repos_seen": repos_seen,
                    "branches_seen": branches_seen,
                    "repo_full_name": repo_full_name,
                },
            )
            raise

    def suggest(
        self,
        *,
        conn: psycopg.Connection[Any],
        actor_id: str,
        query: Optional[str],
        org: Optional[str],
        top_k_repos: int,
        top_k_branches_per_repo: int,
    ) -> dict[str, Any]:
        repos = list_actor_repositories(
            conn,
            actor_id=actor_id,
            org=org,
            updated_since=None,
            limit=max(top_k_repos * 4, 20),
            offset=0,
        )
        if not repos:
            return {
                "actor_id": actor_id,
                "query": query,
                "results": [],
                "auth_required": True,
                "connect_url": self.connect_url(actor_id=actor_id),
                "debug": {
                    "repos_considered": 0,
                    "branches_considered": 0,
                },
            }

        branches_by_repo: dict[str, list[dict[str, Any]]] = {}
        branches_considered = 0
        for repo in repos:
            repo_id = repo.get("id")
            try:
                rid = UUID(str(repo_id))
            except Exception:
                continue
            branches = list_repo_branches_for_actor(
                conn,
                actor_id=actor_id,
                repo_id=rid,
                include_generated=True,
                limit=500,
                offset=0,
            )
            branches_by_repo[str(rid)] = branches
            branches_considered += len(branches)

        ranked = rank_repositories_and_branches(
            repos,
            branches_by_repo,
            query=query,
            top_k_repos=top_k_repos,
            top_k_branches_per_repo=top_k_branches_per_repo,
        )
        return {
            "actor_id": actor_id,
            "query": query,
            "results": ranked,
            "auth_required": False,
            "connect_url": None,
            "debug": {
                "repos_considered": len(repos),
                "branches_considered": branches_considered,
            },
        }

    def list_repos(
        self,
        *,
        conn: psycopg.Connection[Any],
        actor_id: str,
        org: Optional[str],
        updated_since: Optional[datetime],
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return list_actor_repositories(
            conn,
            actor_id=actor_id,
            org=org,
            updated_since=updated_since,
            limit=limit,
            offset=offset,
        )

    def list_branches(
        self,
        *,
        conn: psycopg.Connection[Any],
        actor_id: str,
        repo_id: UUID,
        include_generated: bool,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        return list_repo_branches_for_actor(
            conn,
            actor_id=actor_id,
            repo_id=repo_id,
            include_generated=include_generated,
            limit=limit,
            offset=offset,
        )

    def register_webhook_delivery(
        self,
        *,
        conn: psycopg.Connection[Any],
        delivery_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> tuple[bool, Optional[str], Optional[str]]:
        _, created = create_webhook_delivery(
            conn,
            delivery_id=delivery_id,
            event_type=event_type,
            payload=payload,
        )
        if not created:
            return False, None, None

        repo_full_name: Optional[str] = None
        actor_id: Optional[str] = None

        repo = payload.get("repository")
        if isinstance(repo, dict):
            repo_full_name = cast_str(repo.get("full_name"))
        sender = payload.get("sender")
        if isinstance(sender, dict):
            actor_id = cast_str(sender.get("login"))

        return True, actor_id, repo_full_name

    def mark_webhook_processed(
        self,
        *,
        conn: psycopg.Connection[Any],
        delivery_id: str,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        update_webhook_delivery(
            conn,
            delivery_id=delivery_id,
            status=status,
            error=error,
            mark_processed=True,
        )

    def seed_demo_data(
        self,
        *,
        conn: psycopg.Connection[Any],
        actor_id: str,
        org: str = "demo-org",
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        repos_payload: list[DemoRepo] = [
            (
                9100001,
                org,
                "payments-api",
                f"{org}/payments-api",
                True,
                False,
                False,
                "main",
                now - timedelta(hours=2),
                now - timedelta(hours=2),
                [
                    ("main", True, True, now - timedelta(hours=2), False),
                    ("release/2026-03", False, True, now - timedelta(days=1), False),
                    ("prfactory/auto-442", False, False, now - timedelta(minutes=25), True),
                ],
            ),
            (
                9100002,
                org,
                "customer-portal",
                f"{org}/customer-portal",
                True,
                False,
                False,
                "main",
                now - timedelta(days=3),
                now - timedelta(days=3),
                [
                    ("main", True, True, now - timedelta(days=3), False),
                    ("feature/slack-catalog", False, False, now - timedelta(hours=6), False),
                    ("dependabot/npm_and_yarn/httpx-0.28", False, False, now - timedelta(days=2), True),
                ],
            ),
            (
                9100003,
                org,
                "legacy-billing",
                f"{org}/legacy-billing",
                True,
                True,
                False,
                "master",
                now - timedelta(days=120),
                now - timedelta(days=120),
                [
                    ("master", True, True, now - timedelta(days=120), False),
                    ("hotfix/cve-2026-1234", False, True, now - timedelta(days=40), False),
                ],
            ),
        ]

        repos_seeded = 0
        branches_seeded = 0
        keep_repo_ids: list[UUID] = []

        for (
            github_repo_id,
            repo_owner,
            repo_name,
            full_name,
            is_private,
            is_archived,
            is_disabled,
            default_branch,
            pushed_at,
            updated_at,
            branches,
        ) in repos_payload:
            repo_id = upsert_github_repository(
                conn,
                GitHubRepositoryRecord(
                    github_repo_id=github_repo_id,
                    owner=repo_owner,
                    name=repo_name,
                    full_name=full_name,
                    private=is_private,
                    archived=is_archived,
                    disabled=is_disabled,
                    default_branch=default_branch,
                    pushed_at=pushed_at,
                    updated_at=updated_at,
                    source_token_owner="demo-seed",
                    metadata={"seeded": True},
                ),
            )
            keep_repo_ids.append(repo_id)
            upsert_actor_repo_access(
                conn,
                ActorRepoAccessRecord(
                    actor_id=actor_id,
                    repo_id=repo_id,
                    permission="write",
                    last_seen_at=now,
                ),
            )
            repos_seeded += 1

            keep_branches: list[str] = []
            for name, is_default, protected, last_commit_at, is_generated in branches:
                upsert_github_branch(
                    conn,
                    GitHubBranchRecord(
                        repo_id=repo_id,
                        name=name,
                        head_sha=hashlib.sha1(f"{repo_name}:{name}".encode("utf-8")).hexdigest()[:40],
                        is_default=is_default,
                        protected=protected,
                        last_commit_at=last_commit_at,
                        is_generated=is_generated,
                        metadata={"seeded": True},
                    ),
                )
                keep_branches.append(name)
                branches_seeded += 1
            prune_repo_branches(conn, repo_id=repo_id, keep_branch_names=keep_branches)

        prune_actor_repo_access(conn, actor_id=actor_id, keep_repo_ids=keep_repo_ids)
        return {
            "actor_id": actor_id,
            "org": org,
            "repos_seeded": repos_seeded,
            "branches_seeded": branches_seeded,
        }


def cast_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None
