"""MemoryManager — агрегує 4 шари пам'яті."""

from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

from posipaka.memory.backends.chroma_backend import ChromaBackend
from posipaka.memory.backends.sqlite_backend import SQLiteBackend


class MemoryManager:
    """
    4-шарова система пам'яті:
    1. SHORT-TERM RAM (dict)
    2. SESSION DB (SQLite)
    3. LONG-TERM FACTS (MEMORY.md)
    4. SEMANTIC SEARCH (ChromaDB)
    """

    # MEMORY.md size limit
    MAX_MEMORY_MD_BYTES = 50_000  # ~50KB
    COMPACTION_TRIGGER_BYTES = 40_000  # trigger compaction at 40KB

    def __init__(
        self,
        sqlite_path: Path,
        chroma_path: Path,
        memory_md_path: Path,
        short_term_limit: int = 50,
        chroma_enabled: bool = True,
    ) -> None:
        self._sqlite = SQLiteBackend(sqlite_path)
        self._chroma = ChromaBackend(chroma_path) if chroma_enabled else None
        self._memory_md_path = memory_md_path
        self._short_term_limit = short_term_limit

        # Layer 1: RAM cache
        self._ram: dict[str, list[dict]] = {}

    async def init(self) -> None:
        """Ініціалізація всіх backends."""
        await self._sqlite.init()
        if self._chroma:
            await self._chroma.init()
        logger.info("MemoryManager initialized")

    async def close(self) -> None:
        await self._sqlite.close()
        if self._chroma:
            await self._chroma.close()

    async def add(self, session_id: str, message: dict) -> None:
        """Додати повідомлення до всіх шарів."""
        role = message.get("role", "user")
        content = message.get("content", "")

        # Layer 1: RAM
        if session_id not in self._ram:
            self._ram[session_id] = []
        self._ram[session_id].append(
            {
                "role": role,
                "content": content,
                "created_at": time.time(),
            }
        )
        # Trim
        if len(self._ram[session_id]) > self._short_term_limit:
            self._ram[session_id] = self._ram[session_id][-self._short_term_limit :]

        # Layer 2: SQLite
        await self._sqlite.add_message(session_id, role, content)

        # Layer 4: ChromaDB
        if self._chroma and self._chroma.available:
            await self._chroma.add(session_id, content)

    async def get_recent(self, session_id: str, limit: int = 50) -> list[dict]:
        """Отримати останні повідомлення. RAM first, потім SQLite."""
        # Try RAM
        if session_id in self._ram and self._ram[session_id]:
            return self._ram[session_id][-limit:]

        # Fallback to SQLite
        messages = await self._sqlite.get_recent(session_id, limit)
        if messages:
            self._ram[session_id] = messages[-self._short_term_limit :]
        return messages

    async def search_relevant(self, session_id: str, query: str, limit: int = 5) -> list[str]:
        """Семантичний пошук через ChromaDB."""
        if self._chroma and self._chroma.available:
            return await self._chroma.search(query, session_id, limit)
        return []

    async def maybe_extract_facts(self, session_id: str, text: str) -> None:
        """Витягнення фактів з тексту за ключовими словами."""
        lower = text.lower()
        if any(kw in lower for kw in ("запам'ятай", "запамʼятай", "remember", "нагадай що")):
            await self._sqlite.add_fact(session_id, text)
            logger.debug(f"Fact extracted: {text[:50]}")

    async def get_facts(self, session_id: str | None = None) -> list[dict]:
        """Отримати збережені факти."""
        return await self._sqlite.get_facts(session_id)

    def get_memory_md(self) -> str:
        """Прочитати MEMORY.md."""
        if self._memory_md_path.exists():
            return self._memory_md_path.read_text(encoding="utf-8")
        return ""

    def update_memory_md(self, content: str) -> None:
        """Оновити MEMORY.md з перевіркою розміру."""
        self._memory_md_path.parent.mkdir(parents=True, exist_ok=True)
        content_bytes = len(content.encode("utf-8"))
        if content_bytes > self.MAX_MEMORY_MD_BYTES:
            logger.warning(
                f"MEMORY.md too large ({content_bytes} bytes), "
                f"truncating to {self.MAX_MEMORY_MD_BYTES}"
            )
            content = content[: self.MAX_MEMORY_MD_BYTES]
        self._memory_md_path.write_text(content, encoding="utf-8")

    def check_memory_md_size(self) -> bool:
        """Перевірити чи MEMORY.md потребує compaction."""
        if not self._memory_md_path.exists():
            return False
        size = self._memory_md_path.stat().st_size
        if size > self.COMPACTION_TRIGGER_BYTES:
            logger.info(
                f"MEMORY.md needs compaction: {size} bytes > {self.COMPACTION_TRIGGER_BYTES}"
            )
            return True
        return False

    def compact_memory_md(self) -> str:
        """Стиснути MEMORY.md — видалити дублікати та старі записи."""
        if not self._memory_md_path.exists():
            return "MEMORY.md порожній."

        content = self._memory_md_path.read_text(encoding="utf-8")
        original_size = len(content.encode("utf-8"))

        lines = content.split("\n")
        seen: set[str] = set()
        unique_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            # Зберігати headers та порожні рядки
            if not stripped or stripped.startswith("#"):
                unique_lines.append(line)
                continue
            if stripped not in seen:
                seen.add(stripped)
                unique_lines.append(line)

        compacted = "\n".join(unique_lines)
        new_size = len(compacted.encode("utf-8"))
        self.update_memory_md(compacted)

        saved = original_size - new_size
        return f"MEMORY.md стиснено: {original_size} → {new_size} байт (збережено {saved} байт)"

    async def clear_session(self, session_id: str) -> None:
        """Очистити сесію з усіх шарів."""
        self._ram.pop(session_id, None)
        await self._sqlite.clear_session(session_id)

    async def get_stats(self, session_id: str) -> dict:
        """Статистика сесії."""
        ram_count = len(self._ram.get(session_id, []))
        db_stats = await self._sqlite.get_stats(session_id)
        return {
            "ram_messages": ram_count,
            "db_messages": db_stats.get("count", 0),
            "chroma_available": bool(self._chroma and self._chroma.available),
        }
