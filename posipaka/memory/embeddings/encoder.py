"""Embedding encoder — lazy load sentence-transformers."""

from __future__ import annotations

import hashlib
import time

from loguru import logger


class EmbeddingEncoder:
    """Обгортка над sentence-transformers з lazy loading."""

    DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model = None
        self._last_used: float = 0
        self._cache: dict[str, list[float]] = {}
        self._max_cache: int = 500

    def _load(self) -> None:
        """Lazy load моделі — не при старті."""
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading embedding model: {self._model_name}")
            self._model = SentenceTransformer(self._model_name)
        except ImportError:
            logger.warning("sentence-transformers not installed, embeddings disabled")
            self._model = None

    @property
    def available(self) -> bool:
        """Чи доступний encoder."""
        self._load()
        return self._model is not None

    def encode(self, text: str) -> list[float]:
        """Encode single text with in-memory cache."""
        self._load()
        if self._model is None:
            return []
        self._last_used = time.time()

        # Check cache
        key = hashlib.sha256(text.encode()).hexdigest()[:16]
        if key in self._cache:
            return self._cache[key]

        # Compute
        result = self._model.encode(text).tolist()

        # Store in cache (LRU eviction)
        if len(self._cache) >= self._max_cache:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = result

        return result

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode batch of texts."""
        self._load()
        if self._model is None:
            return [[] for _ in texts]
        self._last_used = time.time()
        embeddings = self._model.encode(texts)
        return [e.tolist() for e in embeddings]

    def maybe_unload(self) -> None:
        """Unload model if idle for more than 1 hour to free memory."""
        if self._model is not None and time.time() - self._last_used > 3600:
            logger.debug(f"Unloading idle embedding model: {self._model_name}")
            del self._model
            self._model = None
            self._cache.clear()
