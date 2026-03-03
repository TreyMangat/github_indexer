from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Chunk:
    text: str
    start_line: Optional[int]
    end_line: Optional[int]
    content_type: str


def chunk_python_source(source: str, max_chars: int, overlap_lines: int) -> list[Chunk]:
    """Chunk Python source using AST where possible.

    Strategy:
    - Prefer top-level class/function blocks as chunks
    - Fallback to line chunking if parsing fails or file is trivial
    """
    lines = source.splitlines()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _chunk_by_lines(
            lines, max_chars=max_chars, overlap_lines=overlap_lines, content_type="code"
        )

    chunks: list[Chunk] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start0 = getattr(node, "lineno", None)
            end0 = getattr(node, "end_lineno", None)
            if start0 is None or end0 is None:
                continue
            start = int(start0)
            end = int(end0)
            block = "\n".join(lines[start - 1 : end])
            # If too large, fall back to line chunking for the block
            if len(block) > max_chars:
                sub = _chunk_by_lines(
                    lines[start - 1 : end],
                    max_chars=max_chars,
                    overlap_lines=overlap_lines,
                    content_type="code",
                    start_line_offset=start - 1,
                )
                chunks.extend(sub)
            else:
                chunks.append(
                    Chunk(text=block, start_line=start, end_line=end, content_type="code")
                )

    if not chunks:
        return _chunk_by_lines(
            lines, max_chars=max_chars, overlap_lines=overlap_lines, content_type="code"
        )

    return chunks


def _chunk_by_lines(
    lines: list[str],
    *,
    max_chars: int,
    overlap_lines: int,
    content_type: str,
    start_line_offset: int = 0,
) -> list[Chunk]:
    out: list[Chunk] = []
    buf: list[str] = []
    start_line: Optional[int] = None

    def flush(end_line_idx: int) -> None:
        nonlocal buf, start_line
        if not buf:
            return
        text = "\n".join(buf).strip()
        if text:
            out.append(
                Chunk(
                    text=text,
                    start_line=(start_line_offset + (start_line or 0)),
                    end_line=start_line_offset + end_line_idx,
                    content_type=content_type,
                )
            )
        # overlap
        if overlap_lines > 0:
            buf = buf[-overlap_lines:]
            start_line = end_line_idx - len(buf) + 1
        else:
            buf = []
            start_line = None

    for idx, line in enumerate(lines, start=1):
        if start_line is None:
            start_line = idx
        # If adding this line would exceed, flush first
        projected = len("\n".join(buf + [line]))
        if buf and projected > max_chars:
            flush(idx - 1)
        buf.append(line)

    flush(len(lines))
    return out
