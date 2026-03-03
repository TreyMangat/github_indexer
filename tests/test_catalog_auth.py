from __future__ import annotations

from datetime import datetime, timedelta, timezone

from repo_recall.catalog.auth import ActorToken, ActorTokenStore


def test_actor_token_store_set_get_clear() -> None:
    store = ActorTokenStore()
    store.set(actor_id="U1", token="tok", ttl_seconds=600)
    assert store.get(actor_id="U1") == "tok"
    store.clear(actor_id="U1")
    assert store.get(actor_id="U1") is None


def test_actor_token_expiration() -> None:
    token = ActorToken(
        token="tok",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert token.is_expired()
