from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..config import Settings
from ..db import connect, init_db
from .auth import ActorTokenStore
from .db import create_github_index_run, list_active_actors, update_github_index_run
from .service import CatalogService
from .token_provider import CatalogTokenProvider

logger = logging.getLogger(__name__)


class CatalogJobRunner:
    def __init__(self, settings: Settings) -> None:
        if settings.job_workers <= 0:
            raise ValueError("JOB_WORKERS must be > 0")
        self._settings = settings
        self._token_provider = CatalogTokenProvider(settings)
        self._service = CatalogService(settings, token_store=self._token_provider.store)
        self._executor = ThreadPoolExecutor(max_workers=settings.job_workers)
        self._futures: dict[uuid.UUID, Future[None]] = {}
        self._lock = threading.Lock()

    @property
    def token_store(self) -> ActorTokenStore:  # compatible accessor for existing call sites/tests
        return self._token_provider.store

    @property
    def service(self) -> CatalogService:
        return self._service

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def submit_sync(
        self,
        *,
        actor_id: str,
        scope: str = "incremental",
        org: Optional[str] = None,
        github_token: Optional[str] = None,
        source_token_owner: Optional[str] = None,
        repo_full_name: Optional[str] = None,
    ) -> uuid.UUID:
        if github_token:
            self._token_provider.set(actor_id=actor_id, token=github_token)

        with connect(self._settings) as conn:
            init_db(conn)
            run_id = create_github_index_run(
                conn,
                actor_id=actor_id,
                scope=scope,
                repo_id=None,
                status="queued",
            )

        fut = self._executor.submit(
            self._run_sync,
            run_id,
            actor_id,
            scope,
            org,
            github_token,
            source_token_owner,
            repo_full_name,
        )
        with self._lock:
            self._futures[run_id] = fut
        return run_id

    def _run_sync(
        self,
        run_id: uuid.UUID,
        actor_id: str,
        scope: str,
        org: Optional[str],
        github_token: Optional[str],
        source_token_owner: Optional[str],
        repo_full_name: Optional[str],
    ) -> None:
        token_lookup = (
            None if github_token else self._token_provider.get(actor_id=actor_id)
        )
        token = github_token or (token_lookup.token if token_lookup else None)
        if not token:
            with connect(self._settings) as conn:
                update_github_index_run(
                    conn,
                    run_id=run_id,
                    status="failed",
                    finished_at=datetime.now(timezone.utc),
                    error="Missing OAuth token for actor",
                    metrics={
                        "auth_required": True,
                        "token_source": token_lookup.source if token_lookup else "request",
                    },
                )
            return

        try:
            with connect(self._settings) as conn:
                self._service.sync_actor(
                    conn=conn,
                    actor_id=actor_id,
                    scope=scope,
                    github_token=token,
                    org=org,
                    source_token_owner=source_token_owner,
                    repo_full_name=repo_full_name,
                    run_id=run_id,
                )
        except Exception:
            logger.exception("Catalog sync run failed run_id=%s actor_id=%s", run_id, actor_id)

    def submit_hourly_sweep(self) -> list[uuid.UUID]:
        since = datetime.now(timezone.utc) - timedelta(days=30)
        with connect(self._settings) as conn:
            actors = list_active_actors(conn, since=since)

        run_ids: list[uuid.UUID] = []
        for actor_id in actors:
            run_ids.append(
                self.submit_sync(
                    actor_id=actor_id,
                    scope="incremental",
                    org=None,
                    github_token=None,
                )
            )
        return run_ids

    def get_future(self, run_id: uuid.UUID) -> Optional[Future[None]]:
        with self._lock:
            return self._futures.get(run_id)
