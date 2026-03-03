from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass(frozen=True)
class ActorToken:
    token: str
    expires_at: datetime

    def is_expired(self, *, now: Optional[datetime] = None) -> bool:
        n = now or datetime.now(timezone.utc)
        return n >= self.expires_at


class ActorTokenStore:
    """In-memory short-lived OAuth token cache keyed by actor_id.

    Tokens are intentionally not persisted to DB.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, ActorToken] = {}

    def set(self, *, actor_id: str, token: str, ttl_seconds: int = 3600) -> None:
        ttl = max(60, int(ttl_seconds))
        rec = ActorToken(
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
        )
        with self._lock:
            self._tokens[actor_id] = rec

    def get(self, *, actor_id: str) -> Optional[str]:
        with self._lock:
            rec = self._tokens.get(actor_id)
            if rec is None:
                return None
            if rec.is_expired():
                self._tokens.pop(actor_id, None)
                return None
            return rec.token

    def clear(self, *, actor_id: str) -> None:
        with self._lock:
            self._tokens.pop(actor_id, None)
