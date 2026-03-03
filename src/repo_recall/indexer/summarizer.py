from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def detect_languages(file_paths: list[Path]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for p in file_paths:
        ext = p.suffix.lower().lstrip(".") or p.name.lower()
        counts[ext] += 1
    return dict(counts.most_common(50))


def read_readme(repo_root: Path, max_chars: int = 6000) -> Optional[str]:
    for name in ["README.md", "README.rst", "README.txt", "README"]:
        p = repo_root / name
        if p.exists():
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
                return txt[:max_chars]
            except Exception:
                return None
    return None


def build_repo_summary(repo_root: Path, key_files: list[str], languages: dict[str, int]) -> str:
    readme = read_readme(repo_root) or ""
    key_files_section = "\n".join(f"- {k}" for k in sorted(set(key_files))[:50])
    lang_section = "\n".join(f"- {k}: {v}" for k, v in list(languages.items())[:30])

    summary = f"""Repo: {repo_root.name}

Key files:
{key_files_section or "- (none detected)"}

Languages/extensions:
{lang_section or "- (unknown)"}

README excerpt:
{readme}
"""
    return summary.strip()
