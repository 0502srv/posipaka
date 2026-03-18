"""Finance skill — персональний фінансовий трекер."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import aiosqlite

_DB_PATH: Path | None = None


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = Path.home() / ".posipaka" / "finance.db"
    return _DB_PATH


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('expense', 'income')),
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'UAH',
            category TEXT NOT NULL DEFAULT 'other',
            description TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]'
        )
    """)
    await db.commit()


async def add_expense(
    amount: float,
    category: str = "other",
    description: str = "",
    currency: str = "UAH",
) -> str:
    """Записати витрату."""
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)
        await db.execute(
            "INSERT INTO transactions (ts, type, amount, currency, category, description) "
            "VALUES (?, 'expense', ?, ?, ?, ?)",
            (time.time(), amount, currency, category, description),
        )
        await db.commit()
    return f"Витрату записано: {amount} {currency} ({category}) — {description}"


async def add_income(
    amount: float,
    category: str = "salary",
    description: str = "",
    currency: str = "UAH",
) -> str:
    """Записати дохід."""
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)
        await db.execute(
            "INSERT INTO transactions (ts, type, amount, currency, category, description) "
            "VALUES (?, 'income', ?, ?, ?, ?)",
            (time.time(), amount, currency, category, description),
        )
        await db.commit()
    return f"Дохід записано: {amount} {currency} ({category}) — {description}"


async def finance_report(days: int = 30, currency: str = "UAH") -> str:
    """Звіт по фінансах за N днів."""
    cutoff = time.time() - days * 86400
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)

        # Totals
        async with db.execute(
            "SELECT type, SUM(amount) FROM transactions "
            "WHERE ts > ? AND currency = ? GROUP BY type",
            (cutoff, currency),
        ) as cursor:
            totals = {row[0]: row[1] async for row in cursor}

        income = totals.get("income", 0)
        expenses = totals.get("expense", 0)
        balance = income - expenses

        # By category
        async with db.execute(
            "SELECT category, SUM(amount) FROM transactions "
            "WHERE ts > ? AND currency = ? AND type = 'expense' "
            "GROUP BY category ORDER BY SUM(amount) DESC",
            (cutoff, currency),
        ) as cursor:
            categories = [(row[0], row[1]) async for row in cursor]

    lines = [
        f"Фінансовий звіт за {days} днів ({currency}):",
        f"  Дохід:   {income:,.2f}",
        f"  Витрати: {expenses:,.2f}",
        f"  Баланс:  {balance:,.2f}",
    ]
    if categories:
        lines.append("\nВитрати по категоріях:")
        for cat, amt in categories:
            lines.append(f"  {cat}: {amt:,.2f}")

    return "\n".join(lines)


async def finance_balance(currency: str = "UAH") -> str:
    """Загальний баланс (всі часи)."""
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)
        async with db.execute(
            "SELECT type, SUM(amount) FROM transactions WHERE currency = ? GROUP BY type",
            (currency,),
        ) as cursor:
            totals = {row[0]: row[1] async for row in cursor}
    income = totals.get("income", 0)
    expenses = totals.get("expense", 0)
    balance = income - expenses
    return f"Баланс: {balance:,.2f} {currency} (дохід: {income:,.2f}, витрати: {expenses:,.2f})"


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="add_expense",
            description="Record a personal expense. Use when user mentions spending money.",
            category="finance",
            handler=add_expense,
            input_schema={
                "type": "object",
                "required": ["amount"],
                "properties": {
                    "amount": {"type": "number", "description": "Amount spent"},
                    "category": {
                        "type": "string",
                        "description": (
                            "Category: food, transport, utilities, "
                            "entertainment, health, education, other"
                        ),
                    },
                    "description": {"type": "string", "description": "What was purchased"},
                    "currency": {"type": "string", "description": "Currency code (default UAH)"},
                },
            },
            tags=["finance", "expense"],
        )
    )

    registry.register(
        ToolDefinition(
            name="add_income",
            description="Record personal income. Use when user reports receiving money.",
            category="finance",
            handler=add_income,
            input_schema={
                "type": "object",
                "required": ["amount"],
                "properties": {
                    "amount": {"type": "number", "description": "Income amount"},
                    "category": {
                        "type": "string",
                        "description": "Category: salary, freelance, gift, investment, other",
                    },
                    "description": {"type": "string"},
                    "currency": {"type": "string", "description": "Currency code (default UAH)"},
                },
            },
            tags=["finance", "income"],
        )
    )

    registry.register(
        ToolDefinition(
            name="finance_report",
            description="Get financial report for the last N days with expenses by category.",
            category="finance",
            handler=finance_report,
            input_schema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Number of days (default 30)"},
                    "currency": {"type": "string", "description": "Currency (default UAH)"},
                },
            },
            tags=["finance", "report"],
        )
    )

    registry.register(
        ToolDefinition(
            name="finance_balance",
            description="Get overall financial balance (total income minus expenses).",
            category="finance",
            handler=finance_balance,
            input_schema={
                "type": "object",
                "properties": {
                    "currency": {"type": "string", "description": "Currency (default UAH)"},
                },
            },
            tags=["finance", "balance"],
        )
    )
