from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from .config import Settings
from .db import connect, create_index_run, update_index_run
from .indexer.indexer import RepoIndexer

logger = logging.getLogger(__name__)


class JobRunner:
    """A small, production-friendly threadpool job runner.

    This exists to support the built-in UI so users can trigger indexing without
    blocking the request thread.

    For higher throughput and distributed execution, you can swap this for a real
    queue (RQ/Celery/etc.) later — the DB `index_runs` table is the compatibility layer.
    """

    def __init__(self, settings: Settings) -> None:
        if settings.job_workers <= 0:
            raise ValueError("JOB_WORKERS must be > 0")
        self._settings = settings
        self._executor = ThreadPoolExecutor(max_workers=settings.job_workers)
        self._futures: dict[uuid.UUID, Future[None]] = {}
        self._lock = threading.Lock()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def submit_index(self, *, repo_ref: str, incremental: bool = True) -> uuid.UUID:
        """Queue an index job and return the run_id."""
        with connect(self._settings) as conn:
            run_id = create_index_run(
                conn, repo_ref=repo_ref, operation="update" if incremental else "index"
            )

        fut = self._executor.submit(self._run_index, run_id, repo_ref, incremental)
        with self._lock:
            self._futures[run_id] = fut
        return run_id

    def _run_index(self, run_id: uuid.UUID, repo_ref: str, incremental: bool) -> None:
        started = datetime.now(timezone.utc)
        try:
            with connect(self._settings) as conn:
                update_index_run(conn, run_id=run_id, status="running", started_at=started)

            idx = RepoIndexer(self._settings)
            stats = idx.index(repo_ref, incremental=incremental)

            finished = datetime.now(timezone.utc)
            with connect(self._settings) as conn:
                update_index_run(
                    conn,
                    run_id=run_id,
                    status="succeeded",
                    repo_id=stats.repo_id,
                    finished_at=finished,
                    error=None,
                )
        except Exception as e:
            finished = datetime.now(timezone.utc)
            logger.exception("Index job failed run_id=%s repo_ref=%s", run_id, repo_ref)
            with connect(self._settings) as conn:
                update_index_run(
                    conn,
                    run_id=run_id,
                    status="failed",
                    finished_at=finished,
                    error=str(e),
                )

    def get_future(self, run_id: uuid.UUID) -> Optional[Future[None]]:
        with self._lock:
            return self._futures.get(run_id)
