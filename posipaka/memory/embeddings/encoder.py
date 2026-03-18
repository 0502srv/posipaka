"""Embedding encoder — lazy load sentence-transformers."""

from __future__ import annotations

from loguru import logger


class EmbeddingEncoder:
    """Обгортка над sentence-transformers з lazy loading."""

    DEFAULT_MODEL = "all-MiniLM-L6-v2"

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model = None

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
        """Encode single text."""
        self._load()
        if self._model is None:
            return []
        return self._model.encode(text).tolist()

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode batch of texts."""
        self._load()
        if self._model is None:
            return [[] for _ in texts]
        embeddings = self._model.encode(texts)
        return [e.tolist() for e in embeddings]
