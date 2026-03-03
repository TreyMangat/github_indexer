from __future__ import annotations

import datetime
import hashlib
import logging
from pathlib import Path
from typing import Optional

from git import Repo

from ..config import Settings

logger = logging.getLogger(__name__)


def _is_git_url(ref: str) -> bool:
    return "://" in ref or ref.endswith(".git") or ref.startswith("git@")


def _safe_dirname(s: str) -> str:
    # stable short name for cache dir
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]
    base = (
        s.replace("://", "_")
        .replace("/", "_")
        .replace(":", "_")
        .replace("@", "_")
        .replace(".git", "")
    )
    base = base[-60:] if len(base) > 60 else base
    return f"{base}_{h}"


def open_repo(repo_ref: str, settings: Settings) -> tuple[Repo, Path, str, str]:
    """Open a local repo path or clone a git URL into the cache."""
    if _is_git_url(repo_ref):
        cache_root = settings.repo_cache_path()
        cache_root.mkdir(parents=True, exist_ok=True)
        dest = cache_root / _safe_dirname(repo_ref)
        if dest.exists():
            repo = Repo(str(dest))
            _fetch(repo)
        else:
            logger.info("Cloning %s into %s", repo_ref, dest)
            repo = Repo.clone_from(repo_ref, str(dest))
        return repo, dest, "git", repo_ref

    # Local path
    path = Path(repo_ref).expanduser().resolve()
    repo = Repo(str(path))
    return repo, path, "local", str(path)


def _fetch(repo: Repo) -> None:
    try:
        for remote in repo.remotes:
            remote.fetch(prune=True)
    except Exception as e:
        logger.warning("Fetch failed: %s", e)


def get_head_commit_sha(repo: Repo) -> str:
    return str(repo.head.commit.hexsha)


def get_last_commit_datetime(repo: Repo) -> Optional[datetime.datetime]:
    try:
        return repo.head.commit.committed_datetime
    except Exception:
        return None


def try_get_default_branch(repo: Repo) -> Optional[str]:
    try:
        return str(repo.active_branch.name)
    except Exception:
        # detached head or no active branch
        return None
