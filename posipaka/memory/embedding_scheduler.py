"""EmbeddingScheduler — batch vectorization за розкладом."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from posipaka.core.scheduler import PosipakScheduler
    from posipaka.memory.backends.chroma_backend import ChromaBackend
    from posipaka.memory.backends.sqlite_backend import SQLiteBackend
    from posipaka.memory.embeddings.encoder import EmbeddingEncoder


class EmbeddingScheduler:
    """
    Асинхронний планувальник векторизації нових повідомлень.

    Режими:
        real_time — embed одразу (висока RAM)
        scheduled — batch embed за розкладом (низька RAM)
        disabled  — тільки BM25, без векторного пошуку
    """

    def __init__(
        self,
        mode: str = "scheduled",
        interval_minutes: int = 15,
        batch_size: int = 50,
        auto_unload: bool = True,
    ) -> None:
        self.mode = mode
        self.interval_minutes = interval_minutes
        self.batch_size = batch_size
        self.auto_unload = auto_unload
        self._encoder: EmbeddingEncoder | None = None
        self._sqlite: SQLiteBackend | None = None
        self._chroma: ChromaBackend | None = None

    def set_backends(
        self, sqlite: SQLiteBackend, chroma: ChromaBackend
    ) -> None:
        self._sqlite = sqlite
        self._chroma = chroma

    async def start(self, scheduler: PosipakScheduler) -> None:
        if self.mode == "disabled":
            logger.info("Embedding disabled — BM25-only search")
            return

        if self.mode == "scheduled":
            scheduler.add_cron(
                job_id="embedding_batch",
                callback=self._run_batch_wrapper,
                cron_expression=f"*/{self.interval_minutes} * * * *",
            )
            logger.info(
                f"Scheduled embedding: every {self.interval_minutes} min, "
                f"batch={self.batch_size}"
            )

    async def _run_batch_wrapper(self) -> None:
        """Wrapper для APScheduler (sync callback)."""
        await self._run_batch()

    async def _run_batch(self) -> None:
        """Знайти unembedded записи і векторизувати пакетом."""
        if not self._sqlite or not self._chroma:
            return

        if self._encoder is None:
            from posipaka.memory.embeddings.encoder import EmbeddingEncoder

            self._encoder = EmbeddingEncoder()

        if not self._encoder.available:
            return

        # Get unembedded messages from SQLite
        assert self._sqlite._db is not None
        cursor = await self._sqlite._db.execute(
            "SELECT id, session_id, content FROM messages "
            "WHERE embedded_at IS NULL AND LENGTH(content) > 30 "
            "ORDER BY created_at ASC LIMIT ?",
            (self.batch_size,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return

        logger.debug(f"Embedding batch: {len(rows)} records")

        texts = [row["content"] for row in rows]
        embeddings = await asyncio.to_thread(self._encoder.encode_batch, texts)

        # Add to ChromaDB
        for row, _embedding in zip(rows, embeddings, strict=False):
            await self._chroma.add(
                session_id=row["session_id"],
                text=row["content"],
                doc_id=str(row["id"]),
            )

        # Mark as embedded
        import time

        now = time.time()
        for row in rows:
            await self._sqlite._db.execute(
                "UPDATE messages SET embedded_at = ? WHERE id = ?",
                (now, row["id"]),
            )
        await self._sqlite._db.commit()

        logger.debug(f"Embedded {len(rows)} records")

        # Auto-unload model
        if self.auto_unload and self._encoder:
            self._encoder._model = None
            import gc

            gc.collect()
            logger.debug("Embedding model unloaded from RAM")

    async def embed_now(self) -> str:
        """Примусовий запуск поза розкладом."""
        await self._run_batch()
        return "Batch embedding завершено."
