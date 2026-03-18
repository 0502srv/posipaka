"""SQLite backend — Layer 2: Session DB."""

from __future__ import annotations

import json
import time
from pathlib import Path

import aiosqlite
from loguru import logger


class SQLiteBackend:
    """Асинхронний SQLite backend для messages, facts, sessions."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Створити таблиці."""
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                fact TEXT NOT NULL,
                source TEXT DEFAULT 'auto',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_facts_session ON facts(session_id);

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                created_at REAL NOT NULL,
                last_active REAL NOT NULL,
                metadata TEXT DEFAULT '{}'
            );
        """)
        await self._db.commit()
        logger.debug(f"SQLite initialized: {self._db_path}")

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """Додати повідомлення."""
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO messages (session_id, role, content, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, json.dumps(metadata or {}), time.time()),
        )
        await self._db.commit()

    async def get_recent(self, session_id: str, limit: int = 50) -> list[dict]:
        """Отримати останні повідомлення сесії."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT role, content, metadata, created_at FROM messages "
            "WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "role": row["role"],
                "content": row["content"],
                "metadata": json.loads(row["metadata"]),
                "created_at": row["created_at"],
            }
            for row in reversed(rows)
        ]

    async def clear_session(self, session_id: str) -> None:
        """Видалити всі повідомлення сесії."""
        assert self._db is not None
        await self._db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await self._db.commit()

    async def get_session_list(self) -> list[str]:
        """Список всіх session_id."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT DISTINCT session_id FROM messages ORDER BY MAX(created_at) DESC"
        )
        rows = await cursor.fetchall()
        return [row["session_id"] for row in rows]

    async def get_stats(self, session_id: str) -> dict:
        """Статистика сесії."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT COUNT(*) as count, MIN(created_at) as first, MAX(created_at) as last "
            "FROM messages WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        if not row or row["count"] == 0:
            return {"count": 0, "first": None, "last": None}
        return {
            "count": row["count"],
            "first": row["first"],
            "last": row["last"],
        }

    async def add_fact(self, session_id: str, fact: str, source: str = "auto") -> None:
        """Додати факт."""
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO facts (session_id, fact, source, created_at) VALUES (?, ?, ?, ?)",
            (session_id, fact, source, time.time()),
        )
        await self._db.commit()

    async def get_facts(self, session_id: str | None = None) -> list[dict]:
        """Отримати факти."""
        assert self._db is not None
        if session_id:
            cursor = await self._db.execute(
                "SELECT fact, source, created_at FROM facts "
                "WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT fact, source, created_at FROM facts ORDER BY created_at"
            )
        rows = await cursor.fetchall()
        return [
            {"fact": row["fact"], "source": row["source"], "created_at": row["created_at"]}
            for row in rows
        ]
