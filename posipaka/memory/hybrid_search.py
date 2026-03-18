"""Hybrid Search — Tantivy BM25 + ChromaDB vector + RRF fusion."""

from __future__ import annotations

import asyncio

from loguru import logger

from posipaka.memory.backends.chroma_backend import ChromaBackend
from posipaka.memory.backends.tantivy_backend import TantivyBackend


def reciprocal_rank_fusion(
    results_a: list[tuple[str, float]],
    results_b: list[tuple[str, float]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """
    RRF — зливає результати двох ranker-ів без знання їх масштабів score.
    k=60 — стандартне значення з TREC 2009.
    """
    scores: dict[str, float] = {}

    for rank, (doc_id, _) in enumerate(results_a):
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)

    for rank, (doc_id, _) in enumerate(results_b):
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


class HybridSearcher:
    """
    Гібридний пошук: Tantivy BM25 + ChromaDB vector, злиття через RRF.

    Обидва запускаються паралельно через asyncio.gather.
    """

    def __init__(
        self,
        tantivy: TantivyBackend | None = None,
        chroma: ChromaBackend | None = None,
    ) -> None:
        self._tantivy = tantivy
        self._chroma = chroma

    async def search(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 10,
    ) -> list[str]:
        """Гібридний пошук — повертає список content strings."""
        tasks = []

        if self._tantivy and self._tantivy.available:
            tasks.append(self._search_tantivy(query, session_id, limit))
        if self._chroma and self._chroma.available:
            tasks.append(self._search_chroma(query, session_id, limit))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect (doc_id/content, score) pairs
        tantivy_results: list[tuple[str, float]] = []
        chroma_results: list[tuple[str, float]] = []
        content_map: dict[str, str] = {}

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"Search backend error: {result}")
                continue
            for doc_id, content, score in result:
                content_map[doc_id] = content
                if i == 0 and self._tantivy and self._tantivy.available:
                    tantivy_results.append((doc_id, score))
                else:
                    chroma_results.append((doc_id, score))

        if tantivy_results and chroma_results:
            # RRF fusion
            fused = reciprocal_rank_fusion(tantivy_results, chroma_results)
            return [content_map[doc_id] for doc_id, _ in fused[:limit] if doc_id in content_map]
        elif tantivy_results:
            return [content_map[doc_id] for doc_id, _ in tantivy_results[:limit]]
        elif chroma_results:
            return [content_map[doc_id] for doc_id, _ in chroma_results[:limit]]

        return []

    async def _search_tantivy(
        self, query: str, session_id: str | None, limit: int
    ) -> list[tuple[str, str, float]]:
        results = await self._tantivy.search(query, session_id, limit)
        return [(r["id"], r["content"], r["score"]) for r in results]

    async def _search_chroma(
        self, query: str, session_id: str | None, limit: int
    ) -> list[tuple[str, str, float]]:
        docs = await self._chroma.search(query, session_id, limit)
        return [(f"chroma_{i}", doc, 1.0 - i * 0.1) for i, doc in enumerate(docs)]
