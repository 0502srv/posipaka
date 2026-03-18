"""ChromaDB backend — Layer 4: Semantic Search."""

from __future__ import annotations

from pathlib import Path

from loguru import logger


class ChromaBackend:
    """Vector store backend з graceful fallback."""

    def __init__(self, persist_dir: Path) -> None:
        self._persist_dir = persist_dir
        self._client = None
        self._collection = None
        self._available = False

    async def init(self) -> None:
        """Ініціалізація ChromaDB."""
        try:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(self._persist_dir))
            self._collection = self._client.get_or_create_collection(
                name="posipaka_messages",
                metadata={"hnsw:space": "cosine"},
            )
            self._available = True
            logger.debug(f"ChromaDB initialized: {self._persist_dir}")
        except ImportError:
            logger.info("chromadb not installed, semantic search disabled")
        except Exception as e:
            logger.warning(f"ChromaDB init failed: {e}")

    @property
    def available(self) -> bool:
        return self._available

    async def add(
        self,
        session_id: str,
        text: str,
        metadata: dict | None = None,
        doc_id: str | None = None,
    ) -> None:
        """Додати текст до vector store."""
        if not self._available or not self._collection:
            return
        try:
            import time as time_mod
            import uuid

            self._collection.add(
                ids=[doc_id or str(uuid.uuid4())],
                documents=[text],
                metadatas=[
                    {
                        "session_id": session_id,
                        "created_at": time_mod.time(),
                        **(metadata or {}),
                    }
                ],
            )
        except Exception as e:
            logger.warning(f"ChromaDB add error: {e}")

    async def search(
        self,
        query: str,
        session_id: str | None = None,
        k: int = 5,
    ) -> list[str]:
        """Семантичний пошук з temporal decay."""
        if not self._available or not self._collection:
            return []
        try:
            import time as time_mod

            where = {"session_id": session_id} if session_id else None
            results = self._collection.query(
                query_texts=[query],
                n_results=min(k * 2, 20),  # Fetch more for re-ranking
                where=where,
                include=["documents", "distances", "metadatas"],
            )
            documents = results.get("documents", [[]])[0]
            distances = results.get("distances", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]

            if not documents:
                return []

            # Re-rank with temporal decay
            now = time_mod.time()
            scored = []
            for doc, dist, meta in zip(documents, distances, metadatas):
                similarity = max(0, 1.0 - dist)  # cosine distance -> similarity
                created = meta.get("created_at", now)
                age_days = (now - created) / 86400
                import math

                decay = math.exp(-age_days / 30)  # half-life ~30 days
                final_score = similarity * (0.7 + 0.3 * decay)  # 70% semantic + 30% recency
                scored.append((doc, final_score))

            scored.sort(key=lambda x: -x[1])
            return [doc for doc, _ in scored[:k]]
        except Exception as e:
            logger.warning(f"ChromaDB search error: {e}")
            return []

    async def close(self) -> None:
        """Закрити з'єднання."""
        self._client = None
        self._collection = None
        self._available = False
