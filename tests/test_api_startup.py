from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://example:example@localhost:5432/example")

from repo_recall.api import app as api_app


def _raise_connect(*args: object, **kwargs: object) -> object:
    raise RuntimeError("db down")


def test_startup_continues_when_db_init_fails_and_fail_fast_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_app.settings, "init_db_on_startup", True)
    monkeypatch.setattr(api_app.settings, "fail_fast_startup", False)
    monkeypatch.setattr(api_app.settings, "enable_ui", False)
    monkeypatch.setattr(api_app.settings, "enable_catalog", False)
    monkeypatch.setattr(api_app, "connect", _raise_connect)

    api_app.startup_issues.clear()
    api_app._startup()

    assert any("DB init on startup failed" in issue for issue in api_app.startup_issues)
    runtime = api_app.runtime()
    assert runtime["startup_issues"] == api_app.startup_issues


def test_startup_raises_when_fail_fast_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_app.settings, "init_db_on_startup", True)
    monkeypatch.setattr(api_app.settings, "fail_fast_startup", True)
    monkeypatch.setattr(api_app.settings, "enable_ui", False)
    monkeypatch.setattr(api_app.settings, "enable_catalog", False)
    monkeypatch.setattr(api_app, "connect", _raise_connect)

    api_app.startup_issues.clear()
    with pytest.raises(RuntimeError, match="db down"):
        api_app._startup()
