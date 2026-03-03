from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .python_chunking import chunk_python_source

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Chunk:
    text: str
    start_line: Optional[int]
    end_line: Optional[int]
    content_type: str  # 'code' | 'doc' | 'config'


DOC_EXTS = {".md", ".rst", ".txt"}
CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".cpp", ".c", ".h"}
CONFIG_EXTS = {".yml", ".yaml", ".toml", ".json", ".ini", ".cfg"}


def guess_content_type(path: Path) -> str:
    ext = path.suffix.lower()
    if path.name.lower() in {"dockerfile"}:
        return "config"
    if ext in DOC_EXTS:
        return "doc"
    if ext in CONFIG_EXTS:
        return "config"
    if ext in CODE_EXTS:
        return "code"
    # Default to code (best effort)
    return "code"


def chunk_file_text(
    file_path: Path,
    text: str,
    *,
    max_chunk_chars: int,
    overlap_lines: int,
) -> list[Chunk]:
    ctype = guess_content_type(file_path)
    ext = file_path.suffix.lower()

    if ext == ".py":
        py_chunks = chunk_python_source(
            text, max_chars=max_chunk_chars, overlap_lines=overlap_lines
        )
        return [
            Chunk(
                text=c.text,
                start_line=c.start_line,
                end_line=c.end_line,
                content_type=c.content_type,
            )
            for c in py_chunks
        ]

    if ctype == "doc" and ext == ".md":
        return chunk_markdown(text, max_chunk_chars=max_chunk_chars, overlap_lines=overlap_lines)

    return chunk_by_lines(
        text, max_chunk_chars=max_chunk_chars, overlap_lines=overlap_lines, content_type=ctype
    )


def chunk_markdown(text: str, *, max_chunk_chars: int, overlap_lines: int) -> list[Chunk]:
    """Chunk markdown by headings, with size fallback."""
    lines = text.splitlines()
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("#") and current:
            chunks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append(current)

    out: list[Chunk] = []
    idx = 0
    for block in chunks:
        block_text = "\n".join(block).strip()
        if not block_text:
            continue
        if len(block_text) <= max_chunk_chars:
            idx += 1
            out.append(Chunk(text=block_text, start_line=None, end_line=None, content_type="doc"))
        else:
            sub = chunk_by_lines(
                block_text,
                max_chunk_chars=max_chunk_chars,
                overlap_lines=overlap_lines,
                content_type="doc",
            )
            for s in sub:
                idx += 1
                out.append(s)
    return out


def chunk_by_lines(
    text: str,
    *,
    max_chunk_chars: int,
    overlap_lines: int,
    content_type: str,
) -> list[Chunk]:
    lines = text.splitlines()
    out: list[Chunk] = []
    buf: list[str] = []
    start_line: Optional[int] = None

    def flush(end_line: int) -> None:
        nonlocal buf, start_line
        if not buf:
            return
        chunk_text = "\n".join(buf).strip()
        if chunk_text:
            out.append(
                Chunk(
                    text=chunk_text,
                    start_line=start_line,
                    end_line=end_line,
                    content_type=content_type,
                )
            )
        # overlap
        if overlap_lines > 0:
            buf = buf[-overlap_lines:]
            start_line = end_line - len(buf) + 1
        else:
            buf = []
            start_line = None

    for idx, line in enumerate(lines, start=1):
        if start_line is None:
            start_line = idx
        projected = len("\n".join(buf + [line]))
        if buf and projected > max_chunk_chars:
            flush(idx - 1)
        buf.append(line)

    flush(len(lines))
    logger.debug("Chunked %d lines into %d chunks", len(lines), len(out))
    return out
