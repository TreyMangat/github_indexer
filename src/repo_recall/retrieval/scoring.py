from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, TypedDict, cast


class HitRow(TypedDict, total=False):
    id: Any
    repo_id: Any
    file_path: Any
    start_line: int | None
    end_line: int | None
    content_type: str | None
    text: str | None
    score: float | int | None


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    repo_id: str
    file_path: str
    start_line: Optional[int]
    end_line: Optional[int]
    content_type: str
    text: str
    vector_score: float
    lexical_score: float
    score: float


def _min_max_norm(values: list[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi - lo < 1e-9:
        # all equal
        return [1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def combine_hits(
    vector_hits: list[HitRow],
    lexical_hits: list[HitRow],
    *,
    w_vector: float = 0.65,
    w_lexical: float = 0.35,
) -> list[Hit]:
    """Merge vector + lexical hits into a single ranked list.

    - Dedup by chunk id
    - Min/max normalize each modality within the candidate set
    - Score = weighted sum of normalized scores
    """
    by_id: dict[str, dict[str, Any]] = {}

    for row in vector_hits:
        cid = str(row["id"])
        by_id.setdefault(cid, {})
        by_id[cid].update(
            {
                "row": row,
                "vector_score": float(row.get("score") or 0.0),
                "lexical_score": by_id[cid].get("lexical_score", 0.0),
            }
        )

    for row in lexical_hits:
        cid = str(row["id"])
        by_id.setdefault(cid, {})
        by_id[cid].update(
            {
                "row": row if "row" not in by_id[cid] else by_id[cid]["row"],
                "lexical_score": float(row.get("score") or 0.0),
                "vector_score": by_id[cid].get("vector_score", 0.0),
            }
        )

    items: list[tuple[str, dict[str, Any]]] = list(by_id.items())
    v_norm = _min_max_norm([float(d.get("vector_score", 0.0)) for _, d in items])
    l_norm = _min_max_norm([float(d.get("lexical_score", 0.0)) for _, d in items])

    hits: list[Hit] = []
    for i, (cid, d) in enumerate(items):
        row = cast(HitRow, d["row"])
        v = float(d.get("vector_score", 0.0))
        lex = float(d.get("lexical_score", 0.0))
        score = w_vector * v_norm[i] + w_lexical * l_norm[i]
        hits.append(
            Hit(
                chunk_id=cid,
                repo_id=str(row["repo_id"]),
                file_path=str(row["file_path"]),
                start_line=row.get("start_line"),
                end_line=row.get("end_line"),
                content_type=str(row.get("content_type") or "code"),
                text=str(row.get("text") or ""),
                vector_score=v,
                lexical_score=lex,
                score=score,
            )
        )

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits


@dataclass(frozen=True)
class RepoAggregate:
    repo_id: str
    score: float
    evidence: list[Hit]


def aggregate_by_repo(
    hits: list[Hit], *, top_k_repos: int, top_k_chunks: int
) -> list[RepoAggregate]:
    buckets: dict[str, list[Hit]] = {}
    for h in hits:
        buckets.setdefault(h.repo_id, []).append(h)

    aggregates: list[RepoAggregate] = []
    for repo_id, repo_hits in buckets.items():
        repo_hits_sorted = sorted(repo_hits, key=lambda h: h.score, reverse=True)
        top = repo_hits_sorted[:top_k_chunks]
        if not top:
            continue
        # Heuristic: best hit dominates + small tail contribution
        max_hit = top[0].score
        tail_sum = sum(h.score for h in top[1:])
        score = max_hit + 0.15 * tail_sum
        aggregates.append(RepoAggregate(repo_id=repo_id, score=score, evidence=top))

    aggregates.sort(key=lambda r: r.score, reverse=True)
    return aggregates[:top_k_repos]
