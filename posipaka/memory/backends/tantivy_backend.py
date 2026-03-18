"""Tantivy backend — Layer 4 alternative: full-text BM25 search."""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger


class TantivyBackend:
    """
    Full-text BM25 пошук через tantivy-py.

    Graceful fallback якщо tantivy не встановлено.
    """

    def __init__(self, index_path: Path) -> None:
        self._path = index_path
        self._index = None
        self._writer = None
        self._available = False

    async def init(self) -> None:
        try:
            await asyncio.to_thread(self._init_sync)
            self._available = True
            logger.debug(f"Tantivy initialized: {self._path}")
        except ImportError:
            logger.info("tantivy not installed, BM25 search disabled")
        except Exception as e:
            logger.warning(f"Tantivy init failed: {e}")

    def _init_sync(self) -> None:
        import tantivy

        schema_builder = tantivy.SchemaBuilder()
        schema_builder.add_text_field("id", stored=True)
        schema_builder.add_text_field("session_id", stored=True, tokenizer_name="raw")
        schema_builder.add_text_field("role", stored=True, tokenizer_name="raw")
        schema_builder.add_text_field("content", stored=True)
        schema_builder.add_float_field("timestamp", stored=True, fast=True)
        schema_builder.add_text_field("tags", stored=True, tokenizer_name="raw")
        schema = schema_builder.build()

        self._path.mkdir(parents=True, exist_ok=True)
        self._index = tantivy.Index(schema, path=str(self._path))
        self._writer = self._index.writer(heap_size=15_000_000)

    @property
    def available(self) -> bool:
        return self._available

    async def add(
        self,
        doc_id: str,
        session_id: str,
        role: str,
        content: str,
        timestamp: float,
        tags: list[str] | None = None,
    ) -> None:
        if not self._available:
            return
        await asyncio.to_thread(
            self._add_sync, doc_id, session_id, role, content, timestamp, tags or []
        )

    def _add_sync(
        self,
        doc_id: str,
        session_id: str,
        role: str,
        content: str,
        timestamp: float,
        tags: list[str],
    ) -> None:
        import tantivy

        doc = tantivy.Document(
            id=doc_id,
            session_id=session_id,
            role=role,
            content=content,
            timestamp=timestamp,
            tags=" ".join(tags),
        )
        self._writer.add_document(doc)
        self._writer.commit()

    async def search(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        if not self._available:
            return []
        return await asyncio.to_thread(self._search_sync, query, session_id, limit)

    @staticmethod
    def _escape_query(query: str) -> str:
        """Екранування спеціальних символів Tantivy."""
        special = set(r'+-&|!(){}[]^"~*?:\/')
        return "".join(f"\\{ch}" if ch in special else ch for ch in query)

    def _search_sync(self, query: str, session_id: str | None, limit: int) -> list[dict]:
        searcher = self._index.searcher()

        safe_query = self._escape_query(query)
        query_parts = [f"content:{safe_query}"]
        if session_id:
            query_parts.append(f"session_id:{session_id}")

        parsed = self._index.parse_query(" AND ".join(query_parts))
        hits = searcher.search(parsed, limit).hits

        results = []
        for score, doc_address in hits:
            doc = searcher.doc(doc_address)
            results.append(
                {
                    "id": doc["id"][0],
                    "content": doc["content"][0],
                    "score": score,
                    "timestamp": doc["timestamp"][0],
                }
            )
        return results

    async def delete_session(self, session_id: str) -> None:
        if not self._available:
            return
        await asyncio.to_thread(self._delete_session_sync, session_id)

    def _delete_session_sync(self, session_id: str) -> None:
        import tantivy

        self._writer.delete_term(tantivy.Term.from_field_text("session_id", session_id))
        self._writer.commit()

    async def close(self) -> None:
        self._index = None
        self._writer = None
        self._available = False
