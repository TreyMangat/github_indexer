from __future__ import annotations

import logging
from pathlib import Path

from pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

logger = logging.getLogger(__name__)

DEFAULT_IGNORE = [
    ".git/",
    ".venv/",
    "venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".cache/",
    "node_modules/",
    "dist/",
    "build/",
    "*.egg-info/",
    ".env",
    ".env.*",
    ".aws/",
    ".ssh/",
    "**/.aws/",
    "**/.ssh/",
    "secrets/",
    "secret/",
    "**/secrets/",
    "**/secret/",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_ed25519",
]


ALLOWLIST_ALWAYS_INDEX = {
    ".env.example",
    ".env.sample",
    ".env.template",
}


KEY_FILES = {
    "README.md",
    "README.rst",
    "pyproject.toml",
    "package.json",
    "Dockerfile",
    "docker-compose.yml",
    ".github/workflows/ci.yml",
    "control/contract.yml",
}


def load_gitignore(repo_root: Path) -> PathSpec:
    patterns: list[str] = []
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        patterns.extend(
            [
                line.strip()
                for line in gitignore.read_text(encoding="utf-8", errors="ignore").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        )
    patterns.extend(DEFAULT_IGNORE)
    return PathSpec.from_lines(GitWildMatchPattern, patterns)


def discover_files(repo_root: Path, max_file_bytes: int) -> list[Path]:
    repo_root = repo_root.resolve()
    spec = load_gitignore(repo_root)

    files: list[Path] = []
    for p in repo_root.rglob("*"):
        rel = p.relative_to(repo_root).as_posix()
        if p.is_dir():
            continue
        # Allowlist some safe env templates even if we ignore `.env.*`.
        if spec.match_file(rel) and p.name not in ALLOWLIST_ALWAYS_INDEX:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size <= 0 or size > max_file_bytes:
            continue
        files.append(p)

    logger.info("Discovered %d files (<= %d bytes)", len(files), max_file_bytes)
    return files


def is_key_file(repo_root: Path, file_path: Path) -> bool:
    rel = file_path.relative_to(repo_root).as_posix()
    if rel in KEY_FILES:
        return True
    # Also treat root-level READMEs as key.
    if rel.lower().startswith("readme"):
        return True
    return False
