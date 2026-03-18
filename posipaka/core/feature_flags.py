"""Feature Flags з SQLite та percentage rollout."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite
from loguru import logger


@dataclass
class FeatureFlag:
    name: str
    description: str = ""
    enabled: bool = False
    percentage: int = 100  # 0-100, для gradual rollout
    created_at: float = field(default_factory=time.time)


DEFAULT_FLAGS = [
    FeatureFlag("VOICE_ENABLED", "Voice input/output (STT/TTS)", enabled=True),
    FeatureFlag("MULTIMODAL_ENABLED", "Image and document processing", enabled=True),
    FeatureFlag("SEMANTIC_CACHE", "Cache similar LLM responses", enabled=True),
    FeatureFlag("PROACTIVE_HEARTBEAT", "Periodic proactive checks", enabled=True),
    FeatureFlag("MCP_TOOLS", "Model Context Protocol tool loading", enabled=False),
    FeatureFlag("WORKFLOW_ENGINE", "YAML workflow execution", enabled=True),
    FeatureFlag("BATCH_PROCESSING", "Batch API for non-urgent tasks", enabled=False),
    FeatureFlag("QUALITY_MONITOR", "Response quality scoring", enabled=False),
    FeatureFlag("DRIFT_DETECTION", "Behavior drift alerts", enabled=False),
    FeatureFlag("RESOURCE_MONITOR", "System resource monitoring", enabled=True),
]


class FeatureFlagManager:
    """Управління feature flags з SQLite backend."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = str(db_path)
        self._initialized = False

    async def _init_db(self) -> None:
        if self._initialized:
            return
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS feature_flags (
                    name TEXT PRIMARY KEY,
                    description TEXT DEFAULT '',
                    enabled INTEGER DEFAULT 0,
                    percentage INTEGER DEFAULT 100,
                    created_at REAL DEFAULT 0
                )
            """)
            await db.commit()

            # Вставити дефолтні прапорці, якщо відсутні
            for flag in DEFAULT_FLAGS:
                await db.execute(
                    """INSERT OR IGNORE INTO feature_flags
                       (name, description, enabled, percentage, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (flag.name, flag.description, int(flag.enabled),
                     flag.percentage, flag.created_at),
                )
            await db.commit()
        self._initialized = True

    async def is_enabled(self, flag_name: str, user_id: str | None = None) -> bool:
        """Перевірити чи ввімкнений прапорець.

        Якщо percentage < 100, використовує hash-based deterministic rollout.
        """
        await self._init_db()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT enabled, percentage FROM feature_flags WHERE name = ?",
                (flag_name,),
            )
            row = await cursor.fetchone()
            if not row:
                return False

            enabled, percentage = bool(row[0]), row[1]
            if not enabled:
                return False
            if percentage >= 100:
                return True
            if not user_id:
                return True  # No user = default enabled

            # Hash-based deterministic rollout
            h = hashlib.sha256(f"{flag_name}:{user_id}".encode()).hexdigest()
            bucket = int(h[:8], 16) % 100
            return bucket < percentage

    async def enable(self, name: str) -> None:
        await self._init_db()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE feature_flags SET enabled = 1 WHERE name = ?", (name,)
            )
            await db.commit()
        logger.info(f"Feature flag enabled: {name}")

    async def disable(self, name: str) -> None:
        await self._init_db()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE feature_flags SET enabled = 0 WHERE name = ?", (name,)
            )
            await db.commit()
        logger.info(f"Feature flag disabled: {name}")

    async def set_rollout(self, name: str, percentage: int) -> None:
        """Встановити відсоток rollout (0-100)."""
        percentage = max(0, min(100, percentage))
        await self._init_db()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE feature_flags SET percentage = ? WHERE name = ?",
                (percentage, name),
            )
            await db.commit()
        logger.info(f"Feature flag rollout: {name} = {percentage}%")

    async def create_flag(
        self, name: str, description: str = "", enabled: bool = False
    ) -> None:
        await self._init_db()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO feature_flags
                   (name, description, enabled, percentage, created_at)
                   VALUES (?, ?, ?, 100, ?)""",
                (name, description, int(enabled), time.time()),
            )
            await db.commit()

    async def delete_flag(self, name: str) -> None:
        await self._init_db()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "DELETE FROM feature_flags WHERE name = ?", (name,)
            )
            await db.commit()

    async def list_flags(self) -> list[FeatureFlag]:
        await self._init_db()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT name, description, enabled, percentage, created_at "
                "FROM feature_flags ORDER BY name"
            )
            rows = await cursor.fetchall()
            return [
                FeatureFlag(
                    name=r[0],
                    description=r[1],
                    enabled=bool(r[2]),
                    percentage=r[3],
                    created_at=r[4],
                )
                for r in rows
            ]
