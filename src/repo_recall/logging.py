from __future__ import annotations

import logging
import os
from typing import Optional


def setup_logging(level: Optional[str] = None) -> None:
    lvl = level or os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=getattr(logging, lvl.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
