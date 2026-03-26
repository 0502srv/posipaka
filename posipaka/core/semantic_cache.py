"""Semantic Response Cache — кешування відповідей на схожі запити."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from posipaka.memory.backends.chroma_backend import ChromaBackend


_SKIP_CACHE_KEYWORDS = frozenset(
    {
        "зараз",
        "now",
        "fresh",
        "актуальн",
        "оновлен",
        "latest",
        "current",
        "поточн",
        "сьогодні",
        "today",
        "щойно",
        "тепер",
    }
)


class SemanticResponseCache:
    """
    Кешує ВІДПОВІДІ агента на семантично схожі питання.

    Ефективно для повторюваних запитів, heartbeat, довідкових питань.
    НЕ використовувати для real-time даних або tool calls.
    """

    SIMILARITY_THRESHOLD = 0.92
    DEFAULT_TTL = 3600  # 1 hour

    TTL_BY_TYPE: dict[str, int] = {
        "weather": 300,  # 5 min
        "fact": 3600,  # 1 hour
        "reference": 86400,  # 24 hours
        "greeting": 86400,
        "default": 1800,  # 30 min
    }

    def __init__(
        self,
        chroma: ChromaBackend | None = None,
        persist_path: Path | None = None,
    ) -> None:
        self._chroma = chroma
        self._memory_cache: dict[str, tuple[str, float, int]] = {}  # key → (response, ts, ttl)
        self._persist_path = persist_path
        self._load_persisted()

    async def check(self, query: str, session_id: str = "") -> str | None:
        """Перевірити чи є cached відповідь. None якщо немає."""
        # Skip cache for queries requesting fresh data
        query_lower = query.lower()
        if any(kw in query_lower for kw in _SKIP_CACHE_KEYWORDS):
            return None

        # Simple in-memory cache first
        key = self._cache_key(query, session_id)
        if key in self._memory_cache:
            response, cached_at, ttl = self._memory_cache[key]
            if time.time() - cached_at < ttl:
                logger.debug(f"Cache hit (memory): {query[:40]}")
                return response
            del self._memory_cache[key]

        # ChromaDB semantic cache (if available)
        if self._chroma and self._chroma.available:
            try:
                results = await self._chroma.search(query, session_id, k=1)
                if results:
                    logger.debug(f"Cache hit (chroma): {query[:40]}")
                    return results[0]
            except Exception:
                pass

        return None

    async def store(
        self,
        query: str,
        response: str,
        session_id: str = "",
        query_type: str = "default",
    ) -> None:
        """Зберегти відповідь у кеш."""
        ttl = self.TTL_BY_TYPE.get(query_type, self.DEFAULT_TTL)
        key = self._cache_key(query, session_id)
        self._memory_cache[key] = (response, time.time(), ttl)

        # Limit memory cache size
        if len(self._memory_cache) > 1000:
            self._evict_expired()

        # Persist to disk periodically (every 10th store)
        if len(self._memory_cache) % 10 == 0:
            self._persist()

    def invalidate(self, session_id: str = "") -> None:
        """Інвалідувати кеш для сесії."""
        if session_id:
            keys = [k for k in self._memory_cache if k.startswith(f"{session_id}:")]
            for k in keys:
                del self._memory_cache[k]
        else:
            self._memory_cache.clear()

    def _evict_expired(self) -> None:
        """Видалити expired entries, then LRU evict if still over 1000."""
        now = time.time()
        expired = [k for k, (_, ts, ttl) in self._memory_cache.items() if now - ts > ttl]
        for k in expired:
            del self._memory_cache[k]

        # LRU eviction: if still over 1000 entries, keep only 900 newest
        if len(self._memory_cache) > 1000:
            sorted_keys = sorted(self._memory_cache, key=lambda k: self._memory_cache[k][1])
            to_remove = sorted_keys[: len(self._memory_cache) - 900]
            for k in to_remove:
                del self._memory_cache[k]

    @staticmethod
    def _cache_key(query: str, session_id: str) -> str:
        h = hashlib.md5(query.lower().strip().encode()).hexdigest()[:12]
        return f"{session_id}:{h}" if session_id else h

    def _persist(self) -> None:
        """Save cache to disk for restart survival."""
        if not self._persist_path:
            return
        try:
            data = {
                k: {"response": r, "ts": ts, "ttl": ttl}
                for k, (r, ts, ttl) in self._memory_cache.items()
                if time.time() - ts < ttl  # only non-expired
            }
            # Keep only last 200 entries
            if len(data) > 200:
                sorted_keys = sorted(data, key=lambda k: data[k]["ts"], reverse=True)
                data = {k: data[k] for k in sorted_keys[:200]}
            self._persist_path.write_text(json.dumps(data), encoding="utf-8")
        except Exception as e:
            logger.debug(f"SemanticCache persist failed: {e}")

    def _load_persisted(self) -> None:
        """Load cache from disk after restart."""
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            now = time.time()
            loaded = 0
            for k, v in data.items():
                ts, ttl = v["ts"], v["ttl"]
                if now - ts < ttl:  # still valid
                    self._memory_cache[k] = (v["response"], ts, ttl)
                    loaded += 1
            if loaded:
                logger.debug(f"SemanticCache: restored {loaded} entries from disk")
        except Exception as e:
            logger.debug(f"SemanticCache load failed: {e}")
