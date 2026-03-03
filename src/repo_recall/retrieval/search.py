from __future__ import annotations

import logging
import uuid
from typing import Any, Optional, cast

from ..config import Settings
from ..db import get_repos_by_ids, lexical_search_chunks, vector_search_chunks
from ..embeddings import OpenAIEmbedder
from .scoring import HitRow, aggregate_by_repo, combine_hits

logger = logging.getLogger(__name__)


def search_repos(
    conn: Any,
    settings: Settings,
    query: str,
    *,
    top_k_repos: int = 5,
    top_k_chunks: int = 3,
    vector_limit: int = 80,
    lexical_limit: int = 80,
    repo_ids: Optional[list[uuid.UUID]] = None,
) -> dict[str, Any]:
    embedder = None
    query_embedding: Optional[list[float]] = None
    if settings.openai_api_key and not settings.mock_mode:
        embedder = OpenAIEmbedder(
            model=settings.embedding_model,
            api_key=settings.openai_api_key,
            dimensions=settings.embedding_dim,
        )
        try:
            query_embedding = embedder.embed_texts([query])[0]
        except Exception as e:
            logger.warning("Query embedding failed; falling back to lexical-only: %s", e)
            query_embedding = None

    vector_hits: list[HitRow] = []
    if query_embedding is not None:
        vector_hits = cast(
            list[HitRow],
            vector_search_chunks(
                conn,
                query_embedding=query_embedding,
                limit=vector_limit,
                repo_ids=repo_ids,
            ),
        )

    lexical_hits = cast(
        list[HitRow],
        lexical_search_chunks(
            conn,
            query=query,
            limit=lexical_limit,
            repo_ids=repo_ids,
        ),
    )

    hits = combine_hits(vector_hits, lexical_hits)
    aggregates = aggregate_by_repo(hits, top_k_repos=top_k_repos, top_k_chunks=top_k_chunks)

    repo_meta = get_repos_by_ids(conn, [uuid.UUID(a.repo_id) for a in aggregates])

    results = []
    for a in aggregates:
        r = repo_meta.get(a.repo_id)
        results.append(
            {
                "repo": {
                    "id": a.repo_id,
                    "name": r.get("name") if r else None,
                    "source": r.get("source") if r else None,
                    "source_ref": r.get("source_ref") if r else None,
                    "default_branch": r.get("default_branch") if r else None,
                    "indexed_commit_sha": r.get("indexed_commit_sha") if r else None,
                    "last_commit_at": str(r.get("last_commit_at")) if r else None,
                    "indexed_at": str(r.get("indexed_at")) if r else None,
                    "languages": r.get("languages") if r else None,
                    "summary": r.get("summary") if r else None,
                },
                "score": a.score,
                "evidence": [
                    {
                        "chunk_id": h.chunk_id,
                        "file_path": h.file_path,
                        "start_line": h.start_line,
                        "end_line": h.end_line,
                        "content_type": h.content_type,
                        "score": h.score,
                        "vector_score": h.vector_score,
                        "lexical_score": h.lexical_score,
                        "text": h.text[:1200],  # trim response
                    }
                    for h in a.evidence
                ],
            }
        )

    return {
        "query": query,
        "results": results,
        "debug": {
            "vector_hits": len(vector_hits),
            "lexical_hits": len(lexical_hits),
            "used_embeddings": query_embedding is not None,
        },
    }
