from __future__ import annotations

import logging
import threading
from typing import Optional

from .jobs import CatalogJobRunner

logger = logging.getLogger(__name__)


class CatalogSweepScheduler:
    """Simple hourly scheduler for actor-scoped catalog reconciliation."""

    def __init__(
        self,
        *,
        runner: CatalogJobRunner,
        interval_seconds: int,
    ) -> None:
        self._runner = runner
        self._interval_seconds = max(60, int(interval_seconds))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="catalog-sweep", daemon=True)
        self._thread.start()
        logger.info("Catalog sweep scheduler started interval=%ss", self._interval_seconds)

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t:
            t.join(timeout=2.0)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                run_ids = self._runner.submit_hourly_sweep()
                if run_ids:
                    logger.info("Catalog sweep queued %d actor sync jobs", len(run_ids))
            except Exception:
                logger.exception("Catalog sweep failed")
            self._stop.wait(self._interval_seconds)
