from __future__ import annotations

import logging
from dataclasses import dataclass

from git import Repo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitChangeSet:
    """A normalized view of git changes."""

    changed: set[str]
    deleted: set[str]


def _parse_name_status(output: str) -> GitChangeSet:
    changed: set[str] = set()
    deleted: set[str] = set()

    for raw in output.splitlines():
        line = raw.strip("\n")
        if not line.strip():
            continue

        # Output is typically tab-delimited: "M\tpath", "R100\told\tnew", etc.
        parts = line.split("\t")
        if not parts:
            continue
        status = parts[0].strip()

        # Renames / copies
        if status.startswith("R") or status.startswith("C"):
            if len(parts) >= 3:
                old_path = parts[1]
                new_path = parts[2]
                deleted.add(old_path)
                changed.add(new_path)
            continue

        # Deleted
        if status.startswith("D"):
            if len(parts) >= 2:
                deleted.add(parts[1])
            continue

        # Added / modified / typechange / etc.
        if len(parts) >= 2:
            changed.add(parts[1])

    return GitChangeSet(changed=changed, deleted=deleted)


def changes_between_commits(repo: Repo, from_sha: str, to_sha: str) -> GitChangeSet:
    """Return changed + deleted paths between two commits."""

    if not from_sha or not to_sha or from_sha == to_sha:
        return GitChangeSet(changed=set(), deleted=set())

    try:
        out = repo.git.diff("--name-status", from_sha, to_sha)
    except Exception as e:
        logger.warning("git diff failed for %s..%s: %s", from_sha, to_sha, e)
        return GitChangeSet(changed=set(), deleted=set())
    return _parse_name_status(out)


def working_tree_changes(repo: Repo) -> GitChangeSet:
    """Return changed + deleted paths in the working tree (staged + unstaged + untracked)."""

    changed: set[str] = set()
    deleted: set[str] = set()

    try:
        unstaged = repo.git.diff("--name-status")
        staged = repo.git.diff("--cached", "--name-status")
        parsed1 = _parse_name_status(unstaged)
        parsed2 = _parse_name_status(staged)
        changed |= parsed1.changed | parsed2.changed
        deleted |= parsed1.deleted | parsed2.deleted
    except Exception as e:
        logger.warning("git diff (working tree) failed: %s", e)

    # Untracked files are effectively "added"
    try:
        for p in repo.untracked_files:
            changed.add(p)
    except Exception:
        pass

    return GitChangeSet(changed=changed, deleted=deleted)
