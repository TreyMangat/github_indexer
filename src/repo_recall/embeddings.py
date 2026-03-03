from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Optional, Protocol

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


def _normalize(text: str) -> str:
    # OpenAI docs commonly recommend replacing newlines for embeddings.
    return text.replace("\n", " ").strip()


@dataclass(frozen=True)
class OpenAIEmbedder:
    model: str
    api_key: Optional[str] = None
    dimensions: Optional[int] = None
    batch_size: int = 64

    def __post_init__(self) -> None:
        if self.batch_size <= 0:
            raise ValueError("batch_size must be > 0")

    @property
    def client(self) -> OpenAI:
        # OpenAI SDK reads OPENAI_API_KEY from env if api_key is None.
        return OpenAI(api_key=self.api_key) if self.api_key else OpenAI()

    @retry(stop=stop_after_attempt(6), wait=wait_exponential_jitter(initial=1, max=20))
    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        if self.dimensions is not None:
            resp = self.client.embeddings.create(
                input=[_normalize(t) for t in batch],
                model=self.model,
                dimensions=self.dimensions,
            )
        else:
            resp = self.client.embeddings.create(
                input=[_normalize(t) for t in batch],
                model=self.model,
            )
        # Response ordering should match inputs by index.
        data = sorted(resp.data, key=lambda d: d.index)
        return [d.embedding for d in data]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        out: list[list[float]] = []
        total = len(texts)
        batches = math.ceil(total / self.batch_size)
        for i in range(batches):
            start = i * self.batch_size
            end = min(start + self.batch_size, total)
            batch = texts[start:end]
            emb = self._embed_batch(batch)
            if len(emb) != len(batch):
                raise RuntimeError("Embedding API returned unexpected batch size")
            out.extend(emb)
            # Light throttling (helps avoid spiky rate limiting)
            time.sleep(0.05)
        return out


@dataclass(frozen=True)
class NullEmbedder:
    """A no-op embedder for lexical-only mode."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("Embeddings are disabled. Set OPENAI_API_KEY to enable semantic search.")
