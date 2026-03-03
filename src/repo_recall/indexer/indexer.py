from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, cast

from ..config import Settings
from ..db import (
    ChunkRecord,
    FileRecord,
    RepoRecord,
    connect,
    delete_chunks_for_file,
    delete_file,
    get_file,
    get_repo_by_source,
    init_db,
    insert_chunks,
    list_files_for_repo,
    upsert_file,
    upsert_repo,
)
from ..embeddings import Embedder, OpenAIEmbedder
from ..redaction import redact_secrets
from .chunking import chunk_file_text
from .file_discovery import discover_files, is_key_file
from .git_changes import changes_between_commits, working_tree_changes
from .ingest import get_head_commit_sha, get_last_commit_datetime, open_repo, try_get_default_branch
from .summarizer import build_repo_summary, detect_languages

logger = logging.getLogger(__name__)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _is_binary_bytes(b: bytes) -> bool:
    # crude binary check: NUL byte
    return b"\x00" in b


def read_text_file(path: Path, max_bytes: int) -> Optional[str]:
    try:
        b = path.read_bytes()
    except Exception:
        return None
    if len(b) > max_bytes:
        return None
    if _is_binary_bytes(b):
        return None
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        # fall back with replacement
        return b.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class IndexStats:
    repo_id: uuid.UUID
    files_seen: int
    files_indexed: int
    chunks_indexed: int


class RepoIndexer:
    def __init__(self, settings: Settings, embedder: Optional[Embedder] = None) -> None:
        self.settings = settings
        self.embedder = embedder or self._default_embedder()

    def _default_embedder(self) -> Optional[Embedder]:
        if self.settings.mock_mode:
            return None
        if self.settings.openai_api_key:
            return OpenAIEmbedder(
                model=self.settings.embedding_model,
                api_key=self.settings.openai_api_key,
                dimensions=self.settings.embedding_dim,
            )
        return None

    def index(self, repo_ref: str, *, incremental: bool = True) -> IndexStats:
        repo, repo_root, source, source_ref = open_repo(repo_ref, self.settings)

        head_sha = get_head_commit_sha(repo)
        is_dirty = False
        try:
            is_dirty = repo.is_dirty(untracked_files=True)
        except Exception:
            is_dirty = False

        with connect(self.settings) as conn:
            init_db(conn)

            existing = get_repo_by_source(conn, source=source, source_ref=source_ref)
            repo_name = existing["name"] if existing else repo_root.name
            prev_indexed_sha: Optional[str] = (
                existing.get("indexed_commit_sha") if existing else None
            )

            files = discover_files(repo_root, max_file_bytes=self.settings.max_file_bytes)
            languages = detect_languages(files)

            key_files_rel: list[str] = []
            for fp in files:
                if is_key_file(repo_root, fp):
                    key_files_rel.append(fp.relative_to(repo_root).as_posix())

            repo_summary = build_repo_summary(
                repo_root, key_files=key_files_rel, languages=languages
            )

            if self.settings.enable_secret_redaction:
                repo_summary, rstats = redact_secrets(repo_summary)
                if rstats.replacements:
                    logger.info("Redacted %d secret(s) in repo summary", rstats.replacements)

            repo_embedding: Optional[list[float]] = None
            if self.embedder:
                try:
                    repo_embedding = self.embedder.embed_texts([repo_summary])[0]
                except Exception as e:
                    logger.warning("Repo summary embedding failed: %s", e)

            repo_id = upsert_repo(
                conn,
                RepoRecord(
                    source=source,
                    source_ref=source_ref,
                    name=repo_name,
                    default_branch=try_get_default_branch(repo),
                    indexed_commit_sha=head_sha,
                    last_commit_at=get_last_commit_datetime(repo),
                    languages=languages,
                    summary=repo_summary,
                    embedding=repo_embedding,
                ),
            )

            # Precompute paths
            paths_by_rel: dict[str, Path] = {
                fp.relative_to(repo_root).as_posix(): fp for fp in files
            }
            current_paths = set(paths_by_rel.keys())

            # Determine which files to (re)index.
            # - Full index for new repos.
            # - Incremental index uses git diffs when possible.
            to_index: set[str] = set(current_paths)

            existing_files = list_files_for_repo(conn, repo_id=repo_id) if incremental else []
            existing_paths = {ef["path"] for ef in existing_files}

            if incremental:
                # Prune deleted files (keeps DB consistent)
                for ef in existing_files:
                    if ef["path"] not in current_paths:
                        delete_file(conn, file_id=uuid.UUID(str(ef["id"])))

                added_paths = current_paths - existing_paths

                # If we have a previous commit SHA, use git diff to decide what to index.
                # If we don't, fall back to indexing everything (first run / migrated DB).
                if existing and prev_indexed_sha:
                    to_index = set(added_paths)

                    if prev_indexed_sha != head_sha:
                        cs = changes_between_commits(repo, prev_indexed_sha, head_sha)
                        to_index |= cs.changed

                    # If the repo is dirty, include working tree changes. This keeps local
                    # dev flows usable without forcing commits.
                    if is_dirty:
                        wt = working_tree_changes(repo)
                        to_index |= wt.changed

                    # Only index files that exist + pass discovery constraints.
                    to_index = {p for p in to_index if p in current_paths}
                else:
                    to_index = set(current_paths)

            files_seen = len(files)
            files_indexed = 0
            chunks_indexed = 0

            if incremental and existing and prev_indexed_sha and prev_indexed_sha != head_sha:
                logger.info(
                    "Incremental indexing via git diff: %s..%s (dirty=%s) paths_to_index=%d",
                    prev_indexed_sha,
                    head_sha,
                    is_dirty,
                    len(to_index),
                )
            elif incremental and existing and is_dirty:
                logger.info(
                    "Incremental indexing includes working tree changes (dirty repo) paths_to_index=%d",
                    len(to_index),
                )

            for rel in sorted(to_index):
                file_path = paths_by_rel.get(rel)
                if file_path is None:
                    continue

                txt_raw = read_text_file(file_path, max_bytes=self.settings.max_file_bytes)
                if not txt_raw:
                    continue

                sha = _sha256_text(txt_raw)
                existing_file = get_file(conn, repo_id=repo_id, path=rel)
                if incremental and existing_file and existing_file.get("sha256") == sha:
                    continue

                txt = txt_raw
                if self.settings.enable_secret_redaction:
                    txt, rstats = redact_secrets(txt_raw)
                    if rstats.replacements:
                        logger.info("Redacted %d secret(s) in %s", rstats.replacements, rel)

                chunks = chunk_file_text(
                    file_path,
                    txt,
                    max_chunk_chars=self.settings.max_chunk_chars,
                    overlap_lines=self.settings.chunk_overlap_lines,
                )
                if not chunks:
                    continue

                # Embed chunks (best-effort)
                embeddings: list[Optional[list[float]]] = [None] * len(chunks)
                if self.embedder:
                    try:
                        vectors = self.embedder.embed_texts([c.text for c in chunks])
                        embeddings = cast(list[Optional[list[float]]], vectors)
                    except Exception as e:
                        logger.warning("Embedding failed for %s: %s", rel, e)

                file_id = upsert_file(
                    conn,
                    FileRecord(
                        repo_id=repo_id,
                        path=rel,
                        language=_guess_language(rel),
                        is_key_file=is_key_file(repo_root, file_path),
                        size_bytes=file_path.stat().st_size,
                        sha256=sha,
                        summary=None,
                        embedding=None,
                    ),
                )

                delete_chunks_for_file(conn, file_id=file_id)
                chunk_records: list[ChunkRecord] = []
                for i, ch in enumerate(chunks):
                    emb = embeddings[i] if isinstance(embeddings[i], list) else None
                    chunk_records.append(
                        ChunkRecord(
                            repo_id=repo_id,
                            file_id=file_id,
                            chunk_index=i,
                            start_line=ch.start_line,
                            end_line=ch.end_line,
                            content_type=ch.content_type,
                            text=ch.text,
                            embedding=emb,
                        )
                    )
                insert_chunks(conn, chunk_records)

                files_indexed += 1
                chunks_indexed += len(chunk_records)

            logger.info(
                "Indexed repo=%s files_seen=%d files_indexed=%d chunks_indexed=%d",
                repo_name,
                files_seen,
                files_indexed,
                chunks_indexed,
            )
            return IndexStats(
                repo_id=repo_id,
                files_seen=files_seen,
                files_indexed=files_indexed,
                chunks_indexed=chunks_indexed,
            )


def _guess_language(path: str) -> Optional[str]:
    ext = Path(path).suffix.lower()
    if ext == ".py":
        return "python"
    if ext in {".js", ".jsx"}:
        return "javascript"
    if ext in {".ts", ".tsx"}:
        return "typescript"
    if ext == ".go":
        return "go"
    if ext == ".rs":
        return "rust"
    if ext in {".java"}:
        return "java"
    if ext in {".md", ".rst", ".txt"}:
        return "docs"
    if ext in {".yml", ".yaml", ".json", ".toml"}:
        return "config"
    return None
