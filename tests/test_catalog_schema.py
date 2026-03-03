from __future__ import annotations

from importlib import resources


def test_schema_contains_catalog_tables() -> None:
    sql = resources.files("repo_recall").joinpath("schema.sql").read_text(encoding="utf-8")
    assert "CREATE SCHEMA IF NOT EXISTS indexer_catalog" in sql
    assert "indexer_catalog.github_repositories" in sql
    assert "indexer_catalog.github_branches" in sql
    assert "indexer_catalog.github_actor_repo_access" in sql
    assert "indexer_catalog.github_index_runs" in sql
    assert "indexer_catalog.github_webhook_deliveries" in sql
    assert "indexer_catalog.github_sync_cursors" in sql
