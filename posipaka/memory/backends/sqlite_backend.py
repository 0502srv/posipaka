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
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
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

            CREATE TABLE IF NOT EXISTS embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_hash TEXT NOT NULL UNIQUE,
                embedding BLOB NOT NULL,
                model TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_embeddings_hash
                ON embeddings(content_hash);
        """)
        await self._db.commit()

        # Migration: add user_id column to facts if missing
        try:
            cursor = await self._db.execute("PRAGMA table_info(facts)")
            columns = {row[1] for row in await cursor.fetchall()}
            if "user_id" not in columns:
                await self._db.execute("ALTER TABLE facts ADD COLUMN user_id TEXT DEFAULT ''")
                await self._db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_facts_user ON facts(user_id)"
                )
                # Backfill user_id from session_id
                await self._db.execute(
                    "UPDATE facts SET user_id = SUBSTR(session_id, 1, INSTR(session_id, ':') - 1) "
                    "WHERE user_id = '' AND session_id LIKE '%:%'"
                )
                await self._db.commit()
                logger.info("Migration: added user_id column to facts table")
        except Exception as e:
            logger.debug(f"Facts migration check: {e}")

        logger.debug(f"SQLite initialized: {self._db_path}")

    def _ensure_db(self) -> aiosqlite.Connection:
        """Перевірити що DB ініціалізована."""
        if self._db is None:
            raise RuntimeError("SQLiteBackend not initialized. Call init() first.")
        return self._db

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
        db = self._ensure_db()
        await db.execute(
            "INSERT INTO messages (session_id, role, content, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, json.dumps(metadata or {}), time.time()),
        )
        await db.commit()

    async def get_recent(self, session_id: str, limit: int = 50) -> list[dict]:
        """Отримати останні повідомлення сесії."""
        db = self._ensure_db()
        cursor = await db.execute(
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
        db = self._ensure_db()
        await db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await db.commit()

    async def get_session_list(self) -> list[str]:
        """Список всіх session_id."""
        db = self._ensure_db()
        cursor = await db.execute(
            "SELECT DISTINCT session_id FROM messages ORDER BY MAX(created_at) DESC"
        )
        rows = await cursor.fetchall()
        return [row["session_id"] for row in rows]

    async def get_stats(self, session_id: str) -> dict:
        """Статистика сесії."""
        db = self._ensure_db()
        cursor = await db.execute(
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

    async def add_fact(
        self, session_id: str, fact: str, source: str = "auto", user_id: str = ""
    ) -> None:
        """Додати факт."""
        db = self._ensure_db()
        # Extract user_id from session_id if not provided (format: "user_id:channel")
        if not user_id and ":" in session_id:
            user_id = session_id.split(":")[0]
        await db.execute(
            "INSERT INTO facts (session_id, user_id, fact, source, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, fact, source, time.time()),
        )
        await db.commit()

    async def get_facts(
        self, session_id: str | None = None, user_id: str | None = None
    ) -> list[dict]:
        """Отримати факти (з ізоляцією по user_id якщо вказано)."""
        db = self._ensure_db()
        if user_id:
            # User-scoped: return facts for this user across all sessions
            cursor = await db.execute(
                "SELECT fact, source, created_at FROM facts WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            )
        elif session_id:
            cursor = await db.execute(
                "SELECT fact, source, created_at FROM facts "
                "WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            )
        else:
            cursor = await db.execute(
                "SELECT fact, source, created_at FROM facts ORDER BY created_at"
            )
        rows = await cursor.fetchall()
        return [
            {"fact": row["fact"], "source": row["source"], "created_at": row["created_at"]}
            for row in rows
        ]

    async def get_cached_embedding(self, content_hash: str) -> list[float] | None:
        """Get cached embedding by content hash."""
        db = self._ensure_db()
        cursor = await db.execute(
            "SELECT embedding FROM embeddings WHERE content_hash = ?",
            (content_hash,),
        )
        row = await cursor.fetchone()
        if row:
            import struct

            blob = row["embedding"]
            count = len(blob) // 4  # float32
            return list(struct.unpack(f"{count}f", blob))
        return None

    async def cache_embedding(
        self,
        content_hash: str,
        embedding: list[float],
        model: str,
    ) -> None:
        """Cache embedding for future use."""
        db = self._ensure_db()
        import struct

        blob = struct.pack(f"{len(embedding)}f", *embedding)
        await db.execute(
            "INSERT OR REPLACE INTO embeddings "
            "(content_hash, embedding, model, created_at) VALUES (?, ?, ?, ?)",
            (content_hash, blob, model, time.time()),
        )
        await db.commit()
