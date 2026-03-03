from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Sequence, cast

import psycopg

from .models import ActorRepoAccessRecord, GitHubBranchRecord, GitHubRepositoryRecord


def _to_uuid(v: Any) -> uuid.UUID:
    if isinstance(v, uuid.UUID):
        return v
    return uuid.UUID(str(v))


def upsert_github_repository(
    conn: psycopg.Connection[Any],
    repo: GitHubRepositoryRecord,
) -> uuid.UUID:
    new_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO indexer_catalog.github_repositories (
              id, github_repo_id, owner, name, full_name, private, archived, disabled,
              default_branch, pushed_at, updated_at, last_synced_at, source_token_owner, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s::jsonb)
            ON CONFLICT (github_repo_id)
            DO UPDATE SET
              owner = EXCLUDED.owner,
              name = EXCLUDED.name,
              full_name = EXCLUDED.full_name,
              private = EXCLUDED.private,
              archived = EXCLUDED.archived,
              disabled = EXCLUDED.disabled,
              default_branch = EXCLUDED.default_branch,
              pushed_at = EXCLUDED.pushed_at,
              updated_at = EXCLUDED.updated_at,
              last_synced_at = now(),
              source_token_owner = EXCLUDED.source_token_owner,
              metadata = EXCLUDED.metadata
            RETURNING id
            """,
            (
                str(new_id),
                repo.github_repo_id,
                repo.owner,
                repo.name,
                repo.full_name,
                repo.private,
                repo.archived,
                repo.disabled,
                repo.default_branch,
                repo.pushed_at,
                repo.updated_at,
                repo.source_token_owner,
                json.dumps(repo.metadata),
            ),
        )
        row = cur.fetchone()
        assert row is not None
        rid = _to_uuid(row["id"])
    conn.commit()
    return rid


def get_catalog_repo_by_full_name(
    conn: psycopg.Connection[Any],
    *,
    full_name: str,
) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM indexer_catalog.github_repositories
            WHERE full_name = %s
            """,
            (full_name,),
        )
        return cast(Optional[dict[str, Any]], cur.fetchone())


def get_catalog_repo_by_id(
    conn: psycopg.Connection[Any],
    repo_id: uuid.UUID,
) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM indexer_catalog.github_repositories
            WHERE id = %s
            """,
            (str(repo_id),),
        )
        return cast(Optional[dict[str, Any]], cur.fetchone())


def upsert_github_branch(
    conn: psycopg.Connection[Any],
    branch: GitHubBranchRecord,
) -> uuid.UUID:
    new_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO indexer_catalog.github_branches (
              id, repo_id, name, head_sha, is_default, protected, last_commit_at,
              last_synced_at, is_generated, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, now(), %s, %s::jsonb)
            ON CONFLICT (repo_id, name)
            DO UPDATE SET
              head_sha = EXCLUDED.head_sha,
              is_default = EXCLUDED.is_default,
              protected = EXCLUDED.protected,
              last_commit_at = EXCLUDED.last_commit_at,
              last_synced_at = now(),
              is_generated = EXCLUDED.is_generated,
              metadata = EXCLUDED.metadata
            RETURNING id
            """,
            (
                str(new_id),
                str(branch.repo_id),
                branch.name,
                branch.head_sha,
                branch.is_default,
                branch.protected,
                branch.last_commit_at,
                branch.is_generated,
                json.dumps(branch.metadata),
            ),
        )
        row = cur.fetchone()
        assert row is not None
        bid = _to_uuid(row["id"])
    conn.commit()
    return bid


def prune_repo_branches(
    conn: psycopg.Connection[Any],
    *,
    repo_id: uuid.UUID,
    keep_branch_names: Sequence[str],
) -> None:
    keep = list(dict.fromkeys(keep_branch_names))
    with conn.cursor() as cur:
        if keep:
            cur.execute(
                """
                DELETE FROM indexer_catalog.github_branches
                WHERE repo_id = %s
                  AND name <> ALL(%s)
                """,
                (str(repo_id), keep),
            )
        else:
            cur.execute(
                """
                DELETE FROM indexer_catalog.github_branches
                WHERE repo_id = %s
                """,
                (str(repo_id),),
            )
    conn.commit()


def upsert_actor_repo_access(
    conn: psycopg.Connection[Any],
    rec: ActorRepoAccessRecord,
) -> None:
    new_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO indexer_catalog.github_actor_repo_access (
              id, actor_id, repo_id, permission, last_seen_at
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (actor_id, repo_id)
            DO UPDATE SET
              permission = EXCLUDED.permission,
              last_seen_at = EXCLUDED.last_seen_at
            """,
            (
                str(new_id),
                rec.actor_id,
                str(rec.repo_id),
                rec.permission,
                rec.last_seen_at,
            ),
        )
    conn.commit()


def prune_actor_repo_access(
    conn: psycopg.Connection[Any],
    *,
    actor_id: str,
    keep_repo_ids: Sequence[uuid.UUID],
) -> None:
    keep = [str(r) for r in keep_repo_ids]
    with conn.cursor() as cur:
        if keep:
            cur.execute(
                """
                DELETE FROM indexer_catalog.github_actor_repo_access
                WHERE actor_id = %s
                  AND repo_id <> ALL(%s)
                """,
                (actor_id, keep),
            )
        else:
            cur.execute(
                """
                DELETE FROM indexer_catalog.github_actor_repo_access
                WHERE actor_id = %s
                """,
                (actor_id,),
            )
    conn.commit()


def list_actor_repositories(
    conn: psycopg.Connection[Any],
    *,
    actor_id: str,
    org: Optional[str] = None,
    updated_since: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    where: list[str] = ["a.actor_id = %s"]
    params: list[Any] = [actor_id]
    if org:
        where.append("r.owner = %s")
        params.append(org)
    if updated_since:
        where.append("r.updated_at >= %s")
        params.append(updated_since)

    params.extend([limit, offset])
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
              r.*,
              a.permission AS actor_permission,
              a.last_seen_at AS actor_last_seen_at
            FROM indexer_catalog.github_repositories r
            JOIN indexer_catalog.github_actor_repo_access a
              ON a.repo_id = r.id
            WHERE {' AND '.join(where)}
            ORDER BY r.updated_at DESC NULLS LAST, r.full_name ASC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        return list(cur.fetchall() or [])


def list_repo_branches_for_actor(
    conn: psycopg.Connection[Any],
    *,
    actor_id: str,
    repo_id: uuid.UUID,
    include_generated: bool = True,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    where = ["a.actor_id = %s", "r.id = %s"]
    params: list[Any] = [actor_id, str(repo_id)]
    if not include_generated:
        where.append("b.is_generated = false")

    params.extend([limit, offset])
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
              b.*,
              r.full_name,
              r.default_branch
            FROM indexer_catalog.github_branches b
            JOIN indexer_catalog.github_repositories r
              ON r.id = b.repo_id
            JOIN indexer_catalog.github_actor_repo_access a
              ON a.repo_id = r.id
            WHERE {' AND '.join(where)}
            ORDER BY b.is_default DESC, b.last_commit_at DESC NULLS LAST, b.name ASC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        return list(cur.fetchall() or [])


def create_github_index_run(
    conn: psycopg.Connection[Any],
    *,
    actor_id: Optional[str],
    scope: str,
    repo_id: Optional[uuid.UUID],
    status: str = "queued",
) -> uuid.UUID:
    run_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO indexer_catalog.github_index_runs (
              id, actor_id, scope, repo_id, status
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                str(run_id),
                actor_id,
                scope,
                str(repo_id) if repo_id else None,
                status,
            ),
        )
    conn.commit()
    return run_id


def update_github_index_run(
    conn: psycopg.Connection[Any],
    *,
    run_id: uuid.UUID,
    status: str,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    error: Optional[str] = None,
    metrics: Optional[dict[str, Any]] = None,
) -> None:
    fields: list[str] = ["status=%s"]
    params: list[Any] = [status]

    if started_at is not None:
        fields.append("started_at=%s")
        params.append(started_at)
    if finished_at is not None:
        fields.append("finished_at=%s")
        params.append(finished_at)
    if error is not None:
        fields.append("error=%s")
        params.append(error)
    if metrics is not None:
        fields.append("metrics_json=%s::jsonb")
        params.append(json.dumps(metrics))

    params.append(str(run_id))

    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE indexer_catalog.github_index_runs
            SET {', '.join(fields)}
            WHERE id=%s
            """,
            params,
        )
    conn.commit()


def get_github_index_run(
    conn: psycopg.Connection[Any],
    *,
    run_id: uuid.UUID,
) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM indexer_catalog.github_index_runs
            WHERE id=%s
            """,
            (str(run_id),),
        )
        return cast(Optional[dict[str, Any]], cur.fetchone())


def list_github_index_runs(
    conn: psycopg.Connection[Any],
    *,
    actor_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    where = ""
    params: list[Any] = [limit]
    if actor_id:
        where = "WHERE actor_id=%s"
        params = [actor_id, limit]

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT *
            FROM indexer_catalog.github_index_runs
            {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            params,
        )
        return list(cur.fetchall() or [])


def create_webhook_delivery(
    conn: psycopg.Connection[Any],
    *,
    delivery_id: str,
    event_type: str,
    payload: Optional[dict[str, Any]],
) -> tuple[uuid.UUID, bool]:
    new_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO indexer_catalog.github_webhook_deliveries (
              id, delivery_id, event_type, status, payload_json
            )
            VALUES (%s, %s, %s, 'received', %s::jsonb)
            ON CONFLICT (delivery_id) DO NOTHING
            RETURNING id
            """,
            (
                str(new_id),
                delivery_id,
                event_type,
                json.dumps(payload or {}),
            ),
        )
        row = cur.fetchone()
        if row:
            conn.commit()
            return _to_uuid(row["id"]), True

        cur.execute(
            """
            SELECT id
            FROM indexer_catalog.github_webhook_deliveries
            WHERE delivery_id=%s
            """,
            (delivery_id,),
        )
        row2 = cur.fetchone()
        assert row2 is not None
        conn.commit()
        return _to_uuid(row2["id"]), False


def update_webhook_delivery(
    conn: psycopg.Connection[Any],
    *,
    delivery_id: str,
    status: str,
    error: Optional[str] = None,
    mark_processed: bool = False,
) -> None:
    fields: list[str] = ["status=%s"]
    params: list[Any] = [status]
    if error is not None:
        fields.append("error=%s")
        params.append(error)
    if mark_processed:
        fields.append("processed_at=%s")
        params.append(datetime.now(timezone.utc))
    params.append(delivery_id)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE indexer_catalog.github_webhook_deliveries
            SET {', '.join(fields)}
            WHERE delivery_id=%s
            """,
            params,
        )
    conn.commit()


def upsert_sync_cursor(
    conn: psycopg.Connection[Any],
    *,
    actor_id: str,
    scope: str,
    org: Optional[str],
    cursor: dict[str, Any],
    etag: Optional[str],
) -> None:
    new_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO indexer_catalog.github_sync_cursors (
              id, actor_id, scope, org, cursor_json, etag, updated_at
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, now())
            ON CONFLICT (actor_id, scope, org)
            DO UPDATE SET
              cursor_json = EXCLUDED.cursor_json,
              etag = EXCLUDED.etag,
              updated_at = now()
            """,
            (
                str(new_id),
                actor_id,
                scope,
                org,
                json.dumps(cursor),
                etag,
            ),
        )
    conn.commit()


def get_sync_cursor(
    conn: psycopg.Connection[Any],
    *,
    actor_id: str,
    scope: str,
    org: Optional[str],
) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM indexer_catalog.github_sync_cursors
            WHERE actor_id=%s AND scope=%s AND org IS NOT DISTINCT FROM %s
            """,
            (actor_id, scope, org),
        )
        return cast(Optional[dict[str, Any]], cur.fetchone())


def list_active_actors(
    conn: psycopg.Connection[Any],
    *,
    since: datetime,
) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT actor_id
            FROM indexer_catalog.github_actor_repo_access
            WHERE last_seen_at >= %s
            ORDER BY actor_id ASC
            """,
            (since,),
        )
        rows = cur.fetchall() or []
    return [str(r["actor_id"]) for r in rows]
