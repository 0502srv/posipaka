"""Pomodoro skill — таймер фокусу з логуванням сесій."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import aiosqlite

_DB_PATH: Path | None = None
_active_timers: dict[str, dict] = {}


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = Path.home() / ".posipaka" / "pomodoro.db"
    return _DB_PATH


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS pomodoro_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at REAL NOT NULL,
            ended_at REAL,
            duration_min INTEGER NOT NULL DEFAULT 25,
            status TEXT NOT NULL DEFAULT 'completed',
            task TEXT NOT NULL DEFAULT ''
        )
    """)
    await db.commit()


async def start_pomodoro(duration_min: int = 25, task: str = "") -> str:
    """Запустити Pomodoro таймер."""
    if "default" in _active_timers:
        remaining = _active_timers["default"]["duration_min"] * 60 - (
            time.time() - _active_timers["default"]["started_at"]
        )
        if remaining > 0:
            return f"Pomodoro вже запущено! Залишилось {remaining / 60:.1f} хв."

    _active_timers["default"] = {
        "started_at": time.time(),
        "duration_min": duration_min,
        "task": task,
    }
    task_info = f" — {task}" if task else ""
    return f"Pomodoro запущено: {duration_min} хв{task_info}. Фокус!"


async def stop_pomodoro() -> str:
    """Зупинити поточний Pomodoro та зберегти сесію."""
    if "default" not in _active_timers:
        return "Немає активного Pomodoro."

    timer = _active_timers.pop("default")
    elapsed = time.time() - timer["started_at"]
    elapsed_min = elapsed / 60

    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)
        status = "completed" if elapsed_min >= timer["duration_min"] else "interrupted"
        await db.execute(
            "INSERT INTO pomodoro_sessions (started_at, ended_at, duration_min, status, task) "
            "VALUES (?, ?, ?, ?, ?)",
            (timer["started_at"], time.time(), timer["duration_min"], status, timer["task"]),
        )
        await db.commit()

    task_info = f" ({timer['task']})" if timer["task"] else ""
    return f"Pomodoro {status}: {elapsed_min:.1f} хв{task_info}"


async def pomodoro_status() -> str:
    """Статус поточного Pomodoro."""
    if "default" not in _active_timers:
        return "Немає активного Pomodoro."

    timer = _active_timers["default"]
    elapsed = time.time() - timer["started_at"]
    remaining = timer["duration_min"] * 60 - elapsed
    task_info = f" — {timer['task']}" if timer["task"] else ""

    if remaining <= 0:
        return f"Pomodoro завершено!{task_info} Час зупинити."
    return f"Pomodoro активний: {remaining / 60:.1f} хв залишилось{task_info}"


async def pomodoro_stats(days: int = 7) -> str:
    """Статистика Pomodoro за N днів."""
    cutoff = time.time() - days * 86400
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)

        async with db.execute(
            "SELECT COUNT(*), SUM(duration_min), "
            "SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) "
            "FROM pomodoro_sessions WHERE started_at > ?",
            (cutoff,),
        ) as cursor:
            row = await cursor.fetchone()
            total = row[0] or 0
            total_min = row[1] or 0
            completed = row[2] or 0

    if total == 0:
        return f"Немає Pomodoro сесій за {days} днів."

    lines = [
        f"Pomodoro за {days} днів:",
        f"  Сесій: {total} (завершено: {completed})",
        f"  Загальний час: {total_min} хв ({total_min / 60:.1f} год)",
        f"  Середня сесія: {total_min / total:.0f} хв",
    ]
    return "\n".join(lines)


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="start_pomodoro",
            description="Start a Pomodoro focus timer. Default 25 minutes.",
            category="productivity",
            handler=start_pomodoro,
            input_schema={
                "type": "object",
                "properties": {
                    "duration_min": {
                        "type": "integer",
                        "description": "Duration in minutes (default 25)",
                    },
                    "task": {"type": "string", "description": "Task description"},
                },
            },
            tags=["pomodoro", "focus"],
        )
    )

    registry.register(
        ToolDefinition(
            name="stop_pomodoro",
            description="Stop current Pomodoro timer and save session.",
            category="productivity",
            handler=stop_pomodoro,
            input_schema={"type": "object", "properties": {}},
            tags=["pomodoro", "focus"],
        )
    )

    registry.register(
        ToolDefinition(
            name="pomodoro_status",
            description="Check remaining time on current Pomodoro timer.",
            category="productivity",
            handler=pomodoro_status,
            input_schema={"type": "object", "properties": {}},
            tags=["pomodoro", "focus"],
        )
    )

    registry.register(
        ToolDefinition(
            name="pomodoro_stats",
            description="Pomodoro statistics for the last N days.",
            category="productivity",
            handler=pomodoro_stats,
            input_schema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Number of days (default 7)"},
                },
            },
            tags=["pomodoro", "stats"],
        )
    )
