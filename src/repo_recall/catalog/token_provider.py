from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from ..config import Settings
from .auth import ActorTokenStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenLookupResult:
    token: Optional[str]
    source: str


class CatalogTokenProvider:
    """Actor token provider with memory-cache + optional broker fallback."""

    def __init__(self, settings: Settings, *, token_store: Optional[ActorTokenStore] = None) -> None:
        self._settings = settings
        self._store = token_store or ActorTokenStore()

    @property
    def store(self) -> ActorTokenStore:
        return self._store

    def set(self, *, actor_id: str, token: str, ttl_seconds: int = 3600) -> None:
        self._store.set(actor_id=actor_id, token=token, ttl_seconds=ttl_seconds)

    def get(self, *, actor_id: str) -> TokenLookupResult:
        mem = self._store.get(actor_id=actor_id)
        if mem:
            return TokenLookupResult(token=mem, source="memory")

        broker_url = (self._settings.github_token_broker_url or "").strip()
        if not broker_url:
            return TokenLookupResult(token=None, source="missing")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        broker_token = (self._settings.github_token_broker_auth_token or "").strip()
        if broker_token:
            headers["Authorization"] = f"Bearer {broker_token}"

        payload = {"actor_id": actor_id}
        try:
            with httpx.Client(timeout=self._settings.catalog_request_timeout_seconds) as client:
                resp = client.post(broker_url, headers=headers, json=payload)
                if resp.status_code == 404:
                    return TokenLookupResult(token=None, source="broker_missing")
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning("Token broker lookup failed actor=%s err=%s", actor_id, e)
            return TokenLookupResult(token=None, source="broker_error")

        token = _cast_str(data.get("token")) if isinstance(data, dict) else None
        if not token:
            return TokenLookupResult(token=None, source="broker_empty")

        ttl = _cast_int(data.get("expires_in_seconds")) if isinstance(data, dict) else None
        self._store.set(actor_id=actor_id, token=token, ttl_seconds=ttl or 900)
        return TokenLookupResult(token=token, source="broker")


def _cast_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _cast_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None
