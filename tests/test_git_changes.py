from __future__ import annotations

from pathlib import Path

from git import Repo

from repo_recall.indexer.git_changes import changes_between_commits


def test_changes_between_commits_detects_added_and_modified(tmp_path: Path) -> None:
    repo = Repo.init(tmp_path)
    (tmp_path / "a.txt").write_text("one")
    repo.index.add(["a.txt"])
    repo.index.commit("init")
    sha1 = repo.head.commit.hexsha

    (tmp_path / "a.txt").write_text("two")
    (tmp_path / "b.txt").write_text("bbb")
    repo.index.add(["a.txt", "b.txt"])
    repo.index.commit("second")
    sha2 = repo.head.commit.hexsha

    cs = changes_between_commits(repo, sha1, sha2)
    assert "a.txt" in cs.changed
    assert "b.txt" in cs.changed
    assert cs.deleted == set()


def test_changes_between_commits_detects_deleted(tmp_path: Path) -> None:
    repo = Repo.init(tmp_path)
    (tmp_path / "a.txt").write_text("one")
    repo.index.add(["a.txt"])
    repo.index.commit("init")
    sha1 = repo.head.commit.hexsha

    # delete file
    (tmp_path / "a.txt").unlink()
    repo.index.remove(["a.txt"])
    repo.index.commit("delete")
    sha2 = repo.head.commit.hexsha

    cs = changes_between_commits(repo, sha1, sha2)
    assert "a.txt" in cs.deleted
