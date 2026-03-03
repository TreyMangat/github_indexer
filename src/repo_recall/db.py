from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from typing import Any, Iterable, Optional, Sequence, cast

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from .config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepoRecord:
    source: str
    source_ref: str
    name: str
    default_branch: Optional[str]
    indexed_commit_sha: Optional[str]
    last_commit_at: Optional[datetime]
    languages: dict[str, int]
    summary: Optional[str]
    embedding: Optional[list[float]]


@dataclass(frozen=True)
class FileRecord:
    repo_id: uuid.UUID
    path: str
    language: Optional[str]
    is_key_file: bool
    size_bytes: int
    sha256: str
    summary: Optional[str]
    embedding: Optional[list[float]]


@dataclass(frozen=True)
class ChunkRecord:
    repo_id: uuid.UUID
    file_id: uuid.UUID
    chunk_index: int
    start_line: Optional[int]
    end_line: Optional[int]
    content_type: str
    text: str
    embedding: Optional[list[float]]


def _to_uuid(v: Any) -> uuid.UUID:
    if isinstance(v, uuid.UUID):
        return v
    return uuid.UUID(str(v))


def connect(settings: Settings) -> psycopg.Connection[Any]:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL or NEON_CONNECTION_STRING must be set")

    conn = psycopg.connect(settings.database_url, row_factory=dict_row)
    try:
        register_vector(conn)
    except psycopg.ProgrammingError as e:
        # Fresh databases may not have the pgvector extension yet.
        # init_db() creates it; registration is retried there.
        if "vector type not found" not in str(e).lower():
            raise
        logger.info("pgvector type not registered yet; continuing until schema init")
    conn.execute("SET statement_timeout = '60s';")
    return conn


def init_db(conn: psycopg.Connection[Any]) -> None:
    schema_sql = resources.files("repo_recall").joinpath("schema.sql").read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(schema_sql)
    conn.commit()
    # Re-register now that CREATE EXTENSION vector has run.
    register_vector(conn)
    logger.info("DB initialized")


def upsert_repo(conn: psycopg.Connection[Any], repo: RepoRecord) -> uuid.UUID:
    new_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO repos (id, source, source_ref, name, default_branch, indexed_commit_sha, last_commit_at, languages, summary, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (source, source_ref)
            DO UPDATE SET
              name = EXCLUDED.name,
              default_branch = EXCLUDED.default_branch,
              indexed_commit_sha = EXCLUDED.indexed_commit_sha,
              last_commit_at = EXCLUDED.last_commit_at,
              indexed_at = now(),
              languages = EXCLUDED.languages,
              summary = EXCLUDED.summary,
              embedding = EXCLUDED.embedding
            RETURNING id
            """,
            (
                str(new_id),
                repo.source,
                repo.source_ref,
                repo.name,
                repo.default_branch,
                repo.indexed_commit_sha,
                repo.last_commit_at,
                json.dumps(repo.languages),
                repo.summary,
                repo.embedding,
            ),
        )
        row = cur.fetchone()
        assert row is not None
        return _to_uuid(row["id"])


def get_repo_by_source(
    conn: psycopg.Connection[Any], source: str, source_ref: str
) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT * FROM repos WHERE source=%s AND source_ref=%s""",
            (source, source_ref),
        )
        return cast(Optional[dict[str, Any]], cur.fetchone())


def upsert_file(conn: psycopg.Connection[Any], file: FileRecord) -> uuid.UUID:
    new_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO files (id, repo_id, path, language, is_key_file, size_bytes, sha256, summary, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (repo_id, path)
            DO UPDATE SET
              language = EXCLUDED.language,
              is_key_file = EXCLUDED.is_key_file,
              size_bytes = EXCLUDED.size_bytes,
              sha256 = EXCLUDED.sha256,
              indexed_at = now(),
              summary = EXCLUDED.summary,
              embedding = EXCLUDED.embedding
            RETURNING id
            """,
            (
                str(new_id),
                str(file.repo_id),
                file.path,
                file.language,
                file.is_key_file,
                file.size_bytes,
                file.sha256,
                file.summary,
                file.embedding,
            ),
        )
        row = cur.fetchone()
        assert row is not None
        return _to_uuid(row["id"])


def get_file(
    conn: psycopg.Connection[Any], repo_id: uuid.UUID, path: str
) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT * FROM files WHERE repo_id=%s AND path=%s""",
            (str(repo_id), path),
        )
        return cast(Optional[dict[str, Any]], cur.fetchone())


def list_files_for_repo(conn: psycopg.Connection[Any], repo_id: uuid.UUID) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("""SELECT id, path, sha256 FROM files WHERE repo_id=%s""", (str(repo_id),))
        return list(cur.fetchall() or [])


def delete_file(conn: psycopg.Connection[Any], file_id: uuid.UUID) -> None:
    with conn.cursor() as cur:
        cur.execute("""DELETE FROM files WHERE id=%s""", (str(file_id),))
    conn.commit()


def delete_chunks_for_file(conn: psycopg.Connection[Any], file_id: uuid.UUID) -> None:
    with conn.cursor() as cur:
        cur.execute("""DELETE FROM chunks WHERE file_id=%s""", (str(file_id),))
    conn.commit()


def insert_chunks(conn: psycopg.Connection[Any], chunks: Iterable[ChunkRecord]) -> None:
    with conn.cursor() as cur:
        for ch in chunks:
            cur.execute(
                """
                INSERT INTO chunks (id, repo_id, file_id, chunk_index, start_line, end_line, content_type, text, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    str(ch.repo_id),
                    str(ch.file_id),
                    ch.chunk_index,
                    ch.start_line,
                    ch.end_line,
                    ch.content_type,
                    ch.text,
                    ch.embedding,
                ),
            )
    conn.commit()


def vector_search_chunks(
    conn: psycopg.Connection[Any],
    query_embedding: list[float],
    limit: int = 50,
    repo_ids: Optional[list[uuid.UUID]] = None,
) -> list[dict[str, Any]]:
    where_clauses: list[str] = ["c.embedding IS NOT NULL"]
    params: list[Any] = [query_embedding, query_embedding]

    if repo_ids:
        where_clauses.append("c.repo_id = ANY(%s)")
        params.append([str(r) for r in repo_ids])

    where = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
      SELECT
        c.id,
        c.repo_id,
        c.file_id,
        f.path AS file_path,
        c.start_line,
        c.end_line,
        c.content_type,
        c.text,
        (1 - (c.embedding <=> %s)) AS score
      FROM chunks c
      JOIN files f ON f.id = c.file_id
      {where}
      ORDER BY c.embedding <=> %s
      LIMIT {limit}
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall() or [])


def lexical_search_chunks(
    conn: psycopg.Connection[Any],
    query: str,
    limit: int = 50,
    repo_ids: Optional[list[uuid.UUID]] = None,
) -> list[dict[str, Any]]:
    where_clauses: list[str] = ["c.text_tsv @@ plainto_tsquery(%s)"]
    params: list[Any] = [query, query]  # query used twice (rank + filter)

    if repo_ids:
        where_clauses.append("c.repo_id = ANY(%s)")
        params.append([str(r) for r in repo_ids])

    where = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
      SELECT
        c.id,
        c.repo_id,
        c.file_id,
        f.path AS file_path,
        c.start_line,
        c.end_line,
        c.content_type,
        c.text,
        ts_rank_cd(c.text_tsv, plainto_tsquery(%s)) AS score
      FROM chunks c
      JOIN files f ON f.id = c.file_id
      {where}
      ORDER BY score DESC
      LIMIT {limit}
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall() or [])


def get_repos_by_ids(
    conn: psycopg.Connection[Any], repo_ids: Sequence[uuid.UUID]
) -> dict[str, dict[str, Any]]:
    if not repo_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT * FROM repos WHERE id = ANY(%s)""",
            ([str(r) for r in repo_ids],),
        )
        rows = cur.fetchall() or []
    return {str(row["id"]): row for row in rows}


# --- Operational / UI helpers ---


def db_ping(conn: psycopg.Connection[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 AS ok")
        _ = cur.fetchone()


def get_pgvector_version(conn: psycopg.Connection[Any]) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
        row = cur.fetchone()
        if not row:
            return None
        return str(row.get("extversion"))


def get_index_stats(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    """Return lightweight counts for UI / metrics."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM repos) AS repos,
              (SELECT COUNT(*) FROM files) AS files,
              (SELECT COUNT(*) FROM chunks) AS chunks,
              (SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL) AS chunks_with_embeddings,
              (SELECT MAX(indexed_at) FROM repos) AS last_repo_indexed_at
            """
        )
        row = cur.fetchone() or {}
    return {
        "repos": int(row.get("repos") or 0),
        "files": int(row.get("files") or 0),
        "chunks": int(row.get("chunks") or 0),
        "chunks_with_embeddings": int(row.get("chunks_with_embeddings") or 0),
        "last_repo_indexed_at": str(row.get("last_repo_indexed_at"))
        if row.get("last_repo_indexed_at")
        else None,
    }


def list_repos(
    conn: psycopg.Connection[Any], *, limit: int = 100, offset: int = 0
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, source, source_ref, default_branch, indexed_commit_sha, last_commit_at, indexed_at, languages
            FROM repos
            ORDER BY indexed_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        return list(cur.fetchall() or [])


def get_repo_details(conn: psycopg.Connection[Any], repo_id: uuid.UUID) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM repos WHERE id=%s", (str(repo_id),))
        repo = cur.fetchone()
        if not repo:
            return None

        cur.execute("SELECT COUNT(*) AS c FROM files WHERE repo_id=%s", (str(repo_id),))
        files_count = cur.fetchone() or {}

        cur.execute("SELECT COUNT(*) AS c FROM chunks WHERE repo_id=%s", (str(repo_id),))
        chunks_count = cur.fetchone() or {}

        cur.execute(
            """
            SELECT id, path, language, is_key_file, size_bytes, indexed_at
            FROM files
            WHERE repo_id=%s
            ORDER BY is_key_file DESC, path ASC
            LIMIT 200
            """,
            (str(repo_id),),
        )
        files = list(cur.fetchall() or [])

    return {
        "repo": repo,
        "counts": {
            "files": int(files_count.get("c") or 0),
            "chunks": int(chunks_count.get("c") or 0),
        },
        "files": files,
    }


def create_index_run(conn: psycopg.Connection[Any], *, repo_ref: str, operation: str) -> uuid.UUID:
    run_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO index_runs (id, repo_ref, operation, status)
            VALUES (%s, %s, %s, 'queued')
            """,
            (str(run_id), repo_ref, operation),
        )
    conn.commit()
    return run_id


def update_index_run(
    conn: psycopg.Connection[Any],
    *,
    run_id: uuid.UUID,
    status: str,
    repo_id: Optional[uuid.UUID] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    error: Optional[str] = None,
) -> None:
    fields: list[str] = ["status=%s"]
    params: list[Any] = [status]

    if repo_id is not None:
        fields.append("repo_id=%s")
        params.append(str(repo_id))
    if started_at is not None:
        fields.append("started_at=%s")
        params.append(started_at)
    if finished_at is not None:
        fields.append("finished_at=%s")
        params.append(finished_at)
    if error is not None:
        fields.append("error=%s")
        params.append(error)

    params.append(str(run_id))

    with conn.cursor() as cur:
        cur.execute(f"UPDATE index_runs SET {', '.join(fields)} WHERE id=%s", params)
    conn.commit()


def get_index_run(conn: psycopg.Connection[Any], run_id: uuid.UUID) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM index_runs WHERE id=%s", (str(run_id),))
        return cast(Optional[dict[str, Any]], cur.fetchone())


def list_index_runs(conn: psycopg.Connection[Any], *, limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM index_runs
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return list(cur.fetchall() or [])
