"""CostTracker — persistent cost tracking в SQLite."""

from __future__ import annotations

import time
from pathlib import Path

import aiosqlite

MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.8, "output": 4.0},
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "_default": {"input": 5.0, "output": 25.0},
}


class CostTracker:
    """
    Відстежує витрати в USD, зберігає в SQLite.

    Таблиця cost_records:
        (id, timestamp, session_id, model, input_tokens, output_tokens, cost_usd)
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(str(self._db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS cost_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                session_id TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cost_usd REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cost_ts
                ON cost_records(timestamp);
            CREATE INDEX IF NOT EXISTS idx_cost_session
                ON cost_records(session_id);
        """)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def record(
        self,
        session_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Записати використання. Повертає cost_usd."""
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["_default"])
        cost = (
            input_tokens * pricing["input"] / 1_000_000
            + output_tokens * pricing["output"] / 1_000_000
        )
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO cost_records "
            "(timestamp, session_id, model, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), session_id, model, input_tokens, output_tokens, cost),
        )
        await self._db.commit()
        return cost

    async def get_daily_cost(self) -> float:
        assert self._db is not None
        start = time.time() - (time.time() % 86400)
        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_records WHERE timestamp >= ?",
            (start,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0.0

    async def get_session_cost(self, session_id: str) -> float:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_records WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0.0

    async def get_total_cost(self) -> float:
        assert self._db is not None
        cursor = await self._db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM cost_records")
        row = await cursor.fetchone()
        return row[0] if row else 0.0

    async def get_weekly_cost(self) -> float:
        assert self._db is not None
        start = time.time() - 7 * 86400
        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_records WHERE timestamp >= ?",
            (start,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0.0

    async def get_last_minute_cost(self) -> float:
        assert self._db is not None
        start = time.time() - 60
        cursor = await self._db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_records WHERE timestamp >= ?",
            (start,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0.0

    async def get_cost_report(self, daily_budget: float = 5.0) -> str:
        today = await self.get_daily_cost()
        week = await self.get_weekly_cost()
        total = await self.get_total_cost()

        pct = (today / daily_budget * 100) if daily_budget > 0 else 0
        bar = self._progress_bar(pct)

        return (
            f"Витрати токенів\n\n"
            f"Сьогодні:  ${today:.4f} / ${daily_budget:.2f} {bar}\n"
            f"Тиждень:   ${week:.4f}\n"
            f"Всього:    ${total:.4f}"
        )

    @staticmethod
    def _progress_bar(pct: float, width: int = 10) -> str:
        filled = int(pct / 100 * width)
        filled = min(filled, width)
        return "[" + "#" * filled + "." * (width - filled) + f"] {pct:.0f}%"
