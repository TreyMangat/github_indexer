from __future__ import annotations

import pytest

from repo_recall.config import Settings


def test_settings_prefers_neon_connection_string_over_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://db:db@localhost:5432/local_db")
    monkeypatch.setenv(
        "NEON_CONNECTION_STRING",
        "postgresql://neon:neon@localhost:5432/neon_db",
    )
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql://neon:neon@localhost:5432/neon_db"


def test_settings_uses_database_url_when_neon_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://db:db@localhost:5432/local_db")
    monkeypatch.delenv("NEON_CONNECTION_STRING", raising=False)
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql://db:db@localhost:5432/local_db"


def test_fail_fast_startup_defaults_to_false() -> None:
    settings = Settings.model_validate({"DATABASE_URL": "postgresql://db:db@localhost:5432/local_db"})
    assert settings.fail_fast_startup is False
