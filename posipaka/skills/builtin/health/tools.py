"""Health & Fitness skill — трекер здоров'я."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import aiosqlite

_DB_PATH: Path | None = None
_INS = "INSERT INTO health_log (ts, metric, value, unit, note) VALUES (?, ?, ?, ?, ?)"


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = Path.home() / ".posipaka" / "health.db"
    return _DB_PATH


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS health_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            metric TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT ''
        )
    """)
    await db.commit()


async def log_weight(weight: float, unit: str = "kg", note: str = "") -> str:
    """Записати вагу."""
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)
        await db.execute(
            "INSERT INTO health_log (ts, metric, value, unit, note) VALUES (?, 'weight', ?, ?, ?)",
            (time.time(), weight, unit, note),
        )
        await db.commit()
    return f"Вагу записано: {weight} {unit}"


async def log_sleep(hours: float, quality: float = 0, note: str = "") -> str:
    """Записати сон. quality: 1-10 (0 = не вказано)."""
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)
        await db.execute(
            _INS,
            (time.time(), "sleep", hours, "hours", note),
        )
        if quality > 0:
            await db.execute(
                _INS,
                (time.time(), "sleep_quality", min(quality, 10), "score", note),
            )
        await db.commit()
    q_str = f", якість: {quality}/10" if quality > 0 else ""
    return f"Сон записано: {hours} годин{q_str}"


async def log_mood(score: float, note: str = "") -> str:
    """Записати настрій (1-10)."""
    score = max(1, min(10, score))
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)
        await db.execute(
            _INS,
            (time.time(), "mood", score, "score", note),
        )
        await db.commit()
    return f"Настрій записано: {score}/10" + (f" — {note}" if note else "")


async def log_exercise(
    exercise_type: str, duration_min: float, calories: float = 0, note: str = ""
) -> str:
    """Записати тренування."""
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)
        await db.execute(
            _INS,
            (time.time(), "exercise", duration_min, "min", f"{exercise_type}: {note}"),
        )
        if calories > 0:
            await db.execute(
                _INS,
                (time.time(), "calories", calories, "kcal", exercise_type),
            )
        await db.commit()
    cal_str = f", ~{calories} kcal" if calories > 0 else ""
    return f"Тренування записано: {exercise_type} {duration_min} хв{cal_str}"


async def log_water(glasses: float = 1, ml: float = 0) -> str:
    """Записати воду (склянок або мл)."""
    amount = ml if ml > 0 else glasses * 250
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)
        await db.execute(
            _INS,
            (time.time(), "water", amount, "ml", ""),
        )
        await db.commit()
    return f"Воду записано: {amount} мл"


async def health_report(days: int = 7) -> str:
    """Звіт по здоров'ю за N днів."""
    cutoff = time.time() - days * 86400
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)

        metrics: dict[str, list[float]] = {}
        async with db.execute(
            "SELECT metric, value FROM health_log WHERE ts > ? ORDER BY ts",
            (cutoff,),
        ) as cursor:
            async for row in cursor:
                metrics.setdefault(row[0], []).append(row[1])

    if not metrics:
        return f"Немає даних за останні {days} днів."

    lines = [f"Звіт по здоров'ю за {days} днів:"]

    if "weight" in metrics:
        w = metrics["weight"]
        lines.append(f"  Вага: {w[-1]:.1f} кг (вимірювань: {len(w)})")
        if len(w) > 1:
            diff = w[-1] - w[0]
            lines.append(f"    Зміна: {diff:+.1f} кг")

    if "sleep" in metrics:
        s = metrics["sleep"]
        avg_s = sum(s) / len(s)
        lines.append(f"  Сон: середній {avg_s:.1f} год/ніч (записів: {len(s)})")

    if "mood" in metrics:
        m = metrics["mood"]
        avg_m = sum(m) / len(m)
        lines.append(f"  Настрій: середній {avg_m:.1f}/10 (записів: {len(m)})")

    if "exercise" in metrics:
        e = metrics["exercise"]
        total = sum(e)
        lines.append(f"  Тренування: {total:.0f} хв всього ({len(e)} сесій)")

    if "water" in metrics:
        total_w = sum(metrics["water"])
        avg_w = total_w / days
        lines.append(f"  Вода: {total_w:.0f} мл всього ({avg_w:.0f} мл/день)")

    return "\n".join(lines)


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="log_weight",
            description="Log body weight measurement.",
            category="health",
            handler=log_weight,
            input_schema={
                "type": "object",
                "required": ["weight"],
                "properties": {
                    "weight": {"type": "number", "description": "Weight value"},
                    "unit": {"type": "string", "description": "kg or lbs (default kg)"},
                    "note": {"type": "string"},
                },
            },
            tags=["health", "weight"],
        )
    )

    registry.register(
        ToolDefinition(
            name="log_sleep",
            description="Log sleep duration and quality.",
            category="health",
            handler=log_sleep,
            input_schema={
                "type": "object",
                "required": ["hours"],
                "properties": {
                    "hours": {"type": "number", "description": "Hours of sleep"},
                    "quality": {"type": "number", "description": "Sleep quality 1-10 (optional)"},
                    "note": {"type": "string"},
                },
            },
            tags=["health", "sleep"],
        )
    )

    registry.register(
        ToolDefinition(
            name="log_mood",
            description="Log current mood score (1-10).",
            category="health",
            handler=log_mood,
            input_schema={
                "type": "object",
                "required": ["score"],
                "properties": {
                    "score": {"type": "number", "description": "Mood score 1-10"},
                    "note": {"type": "string", "description": "Optional note about mood"},
                },
            },
            tags=["health", "mood"],
        )
    )

    registry.register(
        ToolDefinition(
            name="log_exercise",
            description="Log exercise/workout session.",
            category="health",
            handler=log_exercise,
            input_schema={
                "type": "object",
                "required": ["exercise_type", "duration_min"],
                "properties": {
                    "exercise_type": {
                        "type": "string",
                        "description": (
                            "Type: running, cycling, gym, yoga, swimming, walking, other"
                        ),
                    },
                    "duration_min": {
                        "type": "number",
                        "description": "Duration in minutes",
                    },
                    "calories": {"type": "number", "description": "Estimated calories burned"},
                    "note": {"type": "string"},
                },
            },
            tags=["health", "exercise"],
        )
    )

    registry.register(
        ToolDefinition(
            name="log_water",
            description="Log water intake.",
            category="health",
            handler=log_water,
            input_schema={
                "type": "object",
                "properties": {
                    "glasses": {
                        "type": "number",
                        "description": "Number of glasses (250ml each)",
                    },
                    "ml": {
                        "type": "number",
                        "description": "Exact ml (overrides glasses)",
                    },
                },
            },
            tags=["health", "water"],
        )
    )

    registry.register(
        ToolDefinition(
            name="health_report",
            description="Get health and fitness report for the last N days.",
            category="health",
            handler=health_report,
            input_schema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Number of days (default 7)"},
                },
            },
            tags=["health", "report"],
        )
    )
