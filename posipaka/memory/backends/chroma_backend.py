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
            import uuid

            self._collection.add(
                ids=[doc_id or str(uuid.uuid4())],
                documents=[text],
                metadatas=[{"session_id": session_id, **(metadata or {})}],
            )
        except Exception as e:
            logger.warning(f"ChromaDB add error: {e}")

    async def search(
        self,
        query: str,
        session_id: str | None = None,
        k: int = 5,
    ) -> list[str]:
        """Семантичний пошук."""
        if not self._available or not self._collection:
            return []
        try:
            where = {"session_id": session_id} if session_id else None
            results = self._collection.query(
                query_texts=[query],
                n_results=k,
                where=where,
            )
            documents = results.get("documents", [[]])
            return documents[0] if documents else []
        except Exception as e:
            logger.warning(f"ChromaDB search error: {e}")
            return []

    async def close(self) -> None:
        """Закрити з'єднання."""
        self._client = None
        self._collection = None
        self._available = False
