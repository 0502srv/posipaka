"""Habit tracker with streaks — build and track daily habits."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

_DB_PATH: Path | None = None


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = Path.home() / ".posipaka" / "habits.db"
    return _DB_PATH


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at REAL NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS habit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            ts REAL NOT NULL,
            note TEXT DEFAULT '',
            FOREIGN KEY (habit_id) REFERENCES habits(id)
        )
    """)
    await db.commit()


def _calc_streak(log_dates: list[str]) -> int:
    """Calculate current streak from sorted date strings (YYYY-MM-DD)."""
    if not log_dates:
        return 0
    unique = sorted(set(log_dates), reverse=True)
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    if unique[0] != today and unique[0] != yesterday:
        return 0

    streak = 1
    for i in range(1, len(unique)):
        prev = datetime.strptime(unique[i - 1], "%Y-%m-%d")
        curr = datetime.strptime(unique[i], "%Y-%m-%d")
        if (prev - curr).days == 1:
            streak += 1
        else:
            break
    return streak


async def add_habit(name: str) -> str:
    """Add a new habit to track."""
    async with aiosqlite.connect(_get_db_path()) as db:
        await _ensure_schema(db)
        try:
            await db.execute(
                "INSERT INTO habits (name, created_at) VALUES (?, ?)",
                (name, time.time()),
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            return f'Habit "{name}" already exists.'
    return f'Habit "{name}" added. Start logging!'


async def log_habit(name: str, note: str = "") -> str:
    """Log habit completion for today."""
    async with aiosqlite.connect(_get_db_path()) as db:
        await _ensure_schema(db)
        row = await db.execute_fetchall(
            "SELECT id FROM habits WHERE name = ? AND active = 1", (name,)
        )
        if not row:
            return f'Habit "{name}" not found. Create it first with add_habit.'
        habit_id = row[0][0]

        await db.execute(
            "INSERT INTO habit_log (habit_id, ts, note) VALUES (?, ?, ?)",
            (habit_id, time.time(), note),
        )
        await db.commit()

        # calculate streak
        dates = await db.execute_fetchall(
            "SELECT date(ts, 'unixepoch', 'localtime') "
            "FROM habit_log WHERE habit_id = ? "
            "ORDER BY ts DESC",
            (habit_id,),
        )
        date_strs = [d[0] for d in dates]
        streak = _calc_streak(date_strs)

    return f'Logged "{name}" for today. Current streak: {streak} day(s).'


async def habits_report() -> str:
    """Report on all active habits with streaks."""
    async with aiosqlite.connect(_get_db_path()) as db:
        await _ensure_schema(db)
        habits = await db.execute_fetchall(
            "SELECT id, name FROM habits WHERE active = 1 ORDER BY name"
        )
        if not habits:
            return "No habits tracked yet."

        lines: list[str] = ["HABITS REPORT:"]
        for habit_id, name in habits:
            total = await db.execute_fetchall(
                "SELECT COUNT(*) FROM habit_log WHERE habit_id = ?", (habit_id,)
            )
            total_count = total[0][0]

            dates = await db.execute_fetchall(
                "SELECT date(ts, 'unixepoch', 'localtime') "
                "FROM habit_log WHERE habit_id = ? "
                "ORDER BY ts DESC",
                (habit_id,),
            )
            date_strs = [d[0] for d in dates]
            streak = _calc_streak(date_strs)
            last = date_strs[0] if date_strs else "never"

            lines.append(f"  {name}: {total_count} total, streak={streak}, last={last}")

    return "\n".join(lines)


async def habits_streak(name: str) -> str:
    """Detailed streak info for a single habit."""
    async with aiosqlite.connect(_get_db_path()) as db:
        await _ensure_schema(db)
        row = await db.execute_fetchall("SELECT id, created_at FROM habits WHERE name = ?", (name,))
        if not row:
            return f'Habit "{name}" not found.'
        habit_id, created_at = row[0]

        total = await db.execute_fetchall(
            "SELECT COUNT(*) FROM habit_log WHERE habit_id = ?", (habit_id,)
        )
        total_count = total[0][0]

        dates = await db.execute_fetchall(
            "SELECT date(ts, 'unixepoch', 'localtime') "
            "FROM habit_log WHERE habit_id = ? "
            "ORDER BY ts DESC",
            (habit_id,),
        )
        date_strs = [d[0] for d in dates]
        streak = _calc_streak(date_strs)

        created = time.strftime("%Y-%m-%d", time.localtime(created_at))
        days_since = (datetime.now() - datetime.fromtimestamp(created_at)).days + 1
        rate = (total_count / days_since * 100) if days_since > 0 else 0

    return (
        f'STREAK: "{name}"\n'
        f"  Current streak: {streak} day(s)\n"
        f"  Total completions: {total_count}\n"
        f"  Tracking since: {created} ({days_since} days)\n"
        f"  Completion rate: {rate:.0f}%"
    )


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="add_habit",
            description="Add a new habit to track",
            category="productivity",
            handler=add_habit,
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Habit name"},
                },
                "required": ["name"],
            },
            tags=["habits", "tracking", "productivity"],
        )
    )
    registry.register(
        ToolDefinition(
            name="log_habit",
            description="Log habit completion for today",
            category="productivity",
            handler=log_habit,
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Habit name"},
                    "note": {"type": "string", "description": "Optional note", "default": ""},
                },
                "required": ["name"],
            },
            tags=["habits", "tracking", "productivity"],
        )
    )
    registry.register(
        ToolDefinition(
            name="habits_report",
            description="Report on all active habits with streaks",
            category="productivity",
            handler=habits_report,
            input_schema={"type": "object", "properties": {}},
            tags=["habits", "tracking", "productivity"],
        )
    )
    registry.register(
        ToolDefinition(
            name="habits_streak",
            description="Detailed streak info for a single habit",
            category="productivity",
            handler=habits_streak,
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Habit name"},
                },
                "required": ["name"],
            },
            tags=["habits", "tracking", "productivity"],
        )
    )
