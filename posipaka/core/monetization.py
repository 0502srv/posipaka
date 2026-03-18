"""Monetization infrastructure."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import aiosqlite
from loguru import logger


class PricingTier(StrEnum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass
class TierLimits:
    messages_per_day: int
    tools_allowed: list[str]  # "*" = all
    personas_allowed: int
    storage_mb: int
    support_level: str  # "community", "email", "priority", "dedicated"


TIER_LIMITS: dict[PricingTier, TierLimits] = {
    PricingTier.FREE: TierLimits(
        messages_per_day=50,
        tools_allowed=["web_search", "wikipedia", "weather", "news", "crypto"],
        personas_allowed=3,
        storage_mb=100,
        support_level="community",
    ),
    PricingTier.STARTER: TierLimits(
        messages_per_day=500,
        tools_allowed=["*"],
        personas_allowed=10,
        storage_mb=1024,
        support_level="email",
    ),
    PricingTier.PRO: TierLimits(
        messages_per_day=5000,
        tools_allowed=["*"],
        personas_allowed=-1,  # unlimited
        storage_mb=10240,
        support_level="priority",
    ),
    PricingTier.ENTERPRISE: TierLimits(
        messages_per_day=-1,  # unlimited
        tools_allowed=["*"],
        personas_allowed=-1,
        storage_mb=-1,
        support_level="dedicated",
    ),
}


class UsageTracker:
    """Трекінг використання per user (SQLite)."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = str(db_path)

    async def _init_db(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS usage_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    usage_type TEXT NOT NULL,
                    amount REAL DEFAULT 1,
                    timestamp REAL NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_user_ts
                ON usage_records(user_id, timestamp)
            """)
            await db.commit()

    async def record_usage(
        self, user_id: str, usage_type: str, amount: float = 1.0
    ) -> None:
        """Записати факт використання."""
        await self._init_db()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO usage_records (user_id, usage_type, amount, timestamp) "
                "VALUES (?, ?, ?, ?)",
                (user_id, usage_type, amount, time.time()),
            )
            await db.commit()

    async def get_usage(
        self, user_id: str, period: str = "day"
    ) -> dict[str, float]:
        """Отримати використання за період."""
        await self._init_db()
        seconds = {"day": 86400, "week": 604800, "month": 2592000}.get(period, 86400)
        since = time.time() - seconds

        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT usage_type, SUM(amount) FROM usage_records "
                "WHERE user_id = ? AND timestamp > ? GROUP BY usage_type",
                (user_id, since),
            )
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}

    async def check_limit(
        self, user_id: str, usage_type: str, tier: PricingTier = PricingTier.FREE
    ) -> bool:
        """Перевірити чи не перевищено ліміт."""
        limits = TIER_LIMITS[tier]
        if usage_type == "messages":
            if limits.messages_per_day == -1:
                return True
            usage = await self.get_usage(user_id, "day")
            current = usage.get("messages", 0)
            return current < limits.messages_per_day
        return True

    async def get_usage_report(self, user_id: str) -> str:
        """Форматований звіт використання."""
        day_usage = await self.get_usage(user_id, "day")
        month_usage = await self.get_usage(user_id, "month")

        lines = [
            "Usage Report",
            "─" * 30,
            f"Today: {int(day_usage.get('messages', 0))} messages",
            f"Month: {int(month_usage.get('messages', 0))} messages",
        ]

        cost = month_usage.get("cost_usd", 0)
        if cost:
            lines.append(f"Cost this month: ${cost:.2f}")

        return "\n".join(lines)


class PaymentManager:
    """Stub для Stripe/LemonSqueezy інтеграції.

    Потребує API ключі для реальної роботи.
    """

    async def create_checkout_session(
        self, user_id: str, tier: PricingTier
    ) -> str:
        """Створити URL для оплати (stub)."""
        logger.info(f"Payment checkout requested: {user_id} → {tier.value}")
        return f"https://pay.posipaka.dev/checkout?user={user_id}&tier={tier.value}"

    async def handle_webhook(self, payload: dict) -> None:
        """Обробити webhook від платіжної системи (stub)."""
        logger.info(f"Payment webhook received: {payload.get('type', 'unknown')}")

    async def get_subscription(self, user_id: str) -> dict | None:
        """Отримати підписку користувача (stub)."""
        # В реальній імплементації — запит до Stripe
        return None
