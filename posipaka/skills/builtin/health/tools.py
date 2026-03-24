"""Health & Fitness skill — трекер здоров'я з PR tracking.

Розширений: sets/reps/weight logging, personal records, training context.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import aiosqlite

_DB_PATH: Path | None = None
_TZ = ZoneInfo("Europe/Kyiv")

_INS_SLEEP = (
    "INSERT INTO health_log (ts, metric, value, unit, note) VALUES (?, 'sleep', ?, 'hours', ?)"
)
_INS_SLEEP_Q = (
    "INSERT INTO health_log (ts, metric, value, unit, note) "
    "VALUES (?, 'sleep_quality', ?, 'score', ?)"
)
_INS_MOOD = (
    "INSERT INTO health_log (ts, metric, value, unit, note) VALUES (?, 'mood', ?, 'score', ?)"
)
_INS_WATER = (
    "INSERT INTO health_log (ts, metric, value, unit, note) VALUES (?, 'water', ?, 'ml', '')"
)
_INS_EXERCISE = (
    "INSERT INTO health_log (ts, metric, value, unit, note) VALUES (?, 'exercise', ?, 'min', ?)"
)
_INS_CALORIES = (
    "INSERT INTO health_log (ts, metric, value, unit, note) VALUES (?, 'calories', ?, 'kcal', ?)"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS health_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS exercise_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    exercise TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0,
    reps INTEGER NOT NULL DEFAULT 0,
    set_num INTEGER NOT NULL DEFAULT 1,
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS personal_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise TEXT NOT NULL,
    weight REAL NOT NULL,
    reps INTEGER NOT NULL,
    achieved_at REAL NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    UNIQUE(exercise, weight, reps)
);

CREATE INDEX IF NOT EXISTS idx_sets_exercise ON exercise_sets(exercise, ts DESC);
CREATE INDEX IF NOT EXISTS idx_sets_ts ON exercise_sets(ts DESC);
CREATE INDEX IF NOT EXISTS idx_pr_exercise ON personal_records(exercise);
CREATE INDEX IF NOT EXISTS idx_health_ts ON health_log(ts DESC);
"""


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = Path.home() / ".posipaka" / "health.db"
    return _DB_PATH


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    await db.executescript(_SCHEMA)


async def _check_and_update_pr(
    db: aiosqlite.Connection, exercise: str, weight: float, reps: int
) -> str | None:
    """Check if this is a new PR and update if so. Returns PR message or None."""
    # Get current best for this exercise at this weight
    async with db.execute(
        "SELECT MAX(reps) FROM personal_records WHERE exercise = ? AND weight = ?",
        (exercise, weight),
    ) as cursor:
        row = await cursor.fetchone()
        best_reps_at_weight = row[0] if row and row[0] else 0

    # Get current max weight for this exercise
    async with db.execute(
        "SELECT MAX(weight) FROM personal_records WHERE exercise = ?",
        (exercise,),
    ) as cursor:
        row = await cursor.fetchone()
        max_weight = row[0] if row and row[0] else 0

    pr_messages = []

    # New weight PR
    if weight > max_weight:
        await db.execute(
            "INSERT OR REPLACE INTO personal_records (exercise, weight, reps, achieved_at) "
            "VALUES (?, ?, ?, ?)",
            (exercise, weight, reps, time.time()),
        )
        pr_messages.append(f"NEW WEIGHT PR: {exercise} {weight}kg x {reps}")

    # New reps PR at this weight
    elif reps > best_reps_at_weight:
        await db.execute(
            "INSERT OR REPLACE INTO personal_records (exercise, weight, reps, achieved_at) "
            "VALUES (?, ?, ?, ?)",
            (exercise, weight, reps, time.time()),
        )
        if best_reps_at_weight > 0:
            pr_messages.append(
                f"NEW REPS PR: {exercise} {weight}kg x {reps} (was {best_reps_at_weight})"
            )
        else:
            pr_messages.append(f"FIRST PR: {exercise} {weight}kg x {reps}")

    if pr_messages:
        await db.commit()
        return " | ".join(pr_messages)
    return None


# ── Basic health logging (existing) ──────────────────────────────


async def log_weight(weight: float, unit: str = "kg", note: str = "") -> str:
    """Записати вагу."""
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)
        await db.execute(
            "INSERT INTO health_log (ts, metric, value, unit, note) VALUES (?, 'weight', ?, ?, ?)",
            (time.time(), weight, unit, note),
        )
        await db.commit()

    # Trend
    async with (
        aiosqlite.connect(str(_get_db_path())) as db,
        db.execute(
            "SELECT value FROM health_log WHERE metric='weight' ORDER BY ts DESC LIMIT 2"
        ) as cur,
    ):
        rows = await cur.fetchall()
    trend = ""
    if len(rows) >= 2:
        diff = rows[0][0] - rows[1][0]
        arrow = "↑" if diff > 0 else "↓" if diff < 0 else "→"
        trend = f" ({arrow}{abs(diff):.1f})"

    return f"Вагу записано: {weight} {unit}{trend}"


async def log_sleep(hours: float, quality: float = 0, note: str = "") -> str:
    """Записати сон. quality: 1-10 (0 = не вказано)."""
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)
        await db.execute(
            _INS_SLEEP,
            (time.time(), hours, note),
        )
        if quality > 0:
            await db.execute(
                _INS_SLEEP_Q,
                (time.time(), min(quality, 10), note),
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
            _INS_MOOD,
            (time.time(), score, note),
        )
        await db.commit()
    return f"Настрій записано: {score}/10" + (f" — {note}" if note else "")


async def log_water(glasses: float = 1, ml: float = 0) -> str:
    """Записати воду (склянок або мл)."""
    amount = ml if ml > 0 else glasses * 250
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)
        await db.execute(
            _INS_WATER,
            (time.time(), amount),
        )
        await db.commit()
    return f"Воду записано: {amount} мл"


# ── Exercise set logging with PR tracking ────────────────────────


async def log_set(
    exercise: str,
    weight: float = 0,
    reps: int = 0,
    set_num: int = 0,
    note: str = "",
) -> str:
    """Записати підхід (set) вправи з вагою та повтореннями.

    Автоматично перевіряє та оновлює PR (personal record).
    """
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)

        # Auto set_num: count today's sets for this exercise
        if set_num == 0:
            today_start = datetime.now(_TZ).replace(hour=0, minute=0, second=0).timestamp()
            async with db.execute(
                "SELECT COUNT(*) FROM exercise_sets WHERE exercise = ? AND ts > ?",
                (exercise, today_start),
            ) as cur:
                row = await cur.fetchone()
                set_num = (row[0] if row else 0) + 1

        await db.execute(
            "INSERT INTO exercise_sets (ts, exercise, weight, reps, set_num, note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), exercise, weight, reps, set_num, note),
        )
        await db.commit()

        # Check PR
        pr_msg = None
        if weight > 0 and reps > 0:
            pr_msg = await _check_and_update_pr(db, exercise, weight, reps)

    result = f"Set {set_num}: {exercise}"
    if weight > 0:
        result += f" {weight}kg"
    if reps > 0:
        result += f" x {reps}"
    if pr_msg:
        result += f"\n{pr_msg}"
    return result


async def get_pr(exercise: str = "") -> str:
    """Показати персональні рекорди (PR).

    Без аргументів — всі PR. З назвою вправи — PR для неї.
    """
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)

        if exercise:
            async with db.execute(
                "SELECT weight, reps, achieved_at FROM personal_records "
                "WHERE exercise = ? ORDER BY weight DESC, reps DESC",
                (exercise,),
            ) as cur:
                rows = await cur.fetchall()

            if not rows:
                return f"Немає PR для '{exercise}'."

            lines = [f"PR: {exercise}"]
            for w, r, ts in rows:
                date = datetime.fromtimestamp(ts, _TZ).strftime("%d.%m")
                lines.append(f"  {w}kg x {r} ({date})")
            return "\n".join(lines)

        # All PRs — best per exercise (max weight)
        async with db.execute(
            "SELECT exercise, MAX(weight) as max_w, reps, achieved_at "
            "FROM personal_records GROUP BY exercise ORDER BY exercise"
        ) as cur:
            rows = await cur.fetchall()

        if not rows:
            return "Немає записаних PR."

        lines = ["Персональні рекорди:"]
        for ex, w, r, ts in rows:
            date = datetime.fromtimestamp(ts, _TZ).strftime("%d.%m")
            lines.append(f"  {ex}: {w}kg x {r} ({date})")
        return "\n".join(lines)


async def log_exercise(
    exercise_type: str, duration_min: float, calories: float = 0, note: str = ""
) -> str:
    """Записати тренування (загальне)."""
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)
        await db.execute(
            _INS_EXERCISE,
            (time.time(), duration_min, f"{exercise_type}: {note}"),
        )
        if calories > 0:
            await db.execute(
                _INS_CALORIES,
                (time.time(), calories, exercise_type),
            )
        await db.commit()
    cal_str = f", ~{calories} kcal" if calories > 0 else ""
    return f"Тренування записано: {exercise_type} {duration_min} хв{cal_str}"


# ── Reports ──────────────────────────────────────────────────────


async def health_report(days: int = 7) -> str:
    """Звіт по здоров'ю та тренуванням за N днів."""
    cutoff = time.time() - days * 86400
    async with aiosqlite.connect(str(_get_db_path())) as db:
        await _ensure_schema(db)

        # Health metrics
        metrics: dict[str, list[float]] = {}
        async with db.execute(
            "SELECT metric, value FROM health_log WHERE ts > ? ORDER BY ts",
            (cutoff,),
        ) as cursor:
            async for row in cursor:
                metrics.setdefault(row[0], []).append(row[1])

        # Exercise sets
        async with db.execute(
            "SELECT exercise, weight, reps FROM exercise_sets WHERE ts > ?",
            (cutoff,),
        ) as cursor:
            sets = await cursor.fetchall()

        # New PRs
        async with db.execute(
            "SELECT exercise, weight, reps FROM personal_records WHERE achieved_at > ?",
            (cutoff,),
        ) as cursor:
            new_prs = await cursor.fetchall()

    lines = [f"Звіт за {days} днів:"]

    if "weight" in metrics:
        w = metrics["weight"]
        lines.append(f"  Вага: {w[-1]:.1f} кг (записів: {len(w)})")
        if len(w) > 1:
            diff = w[-1] - w[0]
            arrow = "↑" if diff > 0 else "↓"
            lines.append(f"    Зміна: {arrow}{abs(diff):.1f} кг")

    if "sleep" in metrics:
        s = metrics["sleep"]
        avg_s = sum(s) / len(s)
        lines.append(f"  Сон: {avg_s:.1f} год/ніч (записів: {len(s)})")

    if "mood" in metrics:
        m = metrics["mood"]
        avg_m = sum(m) / len(m)
        lines.append(f"  Настрій: {avg_m:.1f}/10")

    if "water" in metrics:
        total_w = sum(metrics["water"])
        lines.append(f"  Вода: {total_w:.0f} мл/тиждень")

    if sets:
        exercises = {}
        total_volume = 0
        for ex, w, r in sets:
            exercises[ex] = exercises.get(ex, 0) + 1
            total_volume += w * r
        lines.append(f"  Тренування: {len(sets)} підходів, {len(exercises)} вправ")
        lines.append(f"    Об'єм: {total_volume:.0f} кг (вага x повторення)")
        for ex, count in sorted(exercises.items(), key=lambda x: -x[1]):
            lines.append(f"    {ex}: {count} підходів")

    if new_prs:
        lines.append(f"  Нові PR: {len(new_prs)}")
        for ex, w, r in new_prs:
            lines.append(f"    {ex}: {w}kg x {r}")

    if len(lines) == 1:
        return f"Немає даних за останні {days} днів."

    return "\n".join(lines)


# ── Registration ─────────────────────────────────────────────────


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="log_weight",
            description=(
                "Log body weight. Use when user reports their weight. "
                "Shows trend compared to previous measurement."
            ),
            category="health",
            handler=log_weight,
            input_schema={
                "type": "object",
                "required": ["weight"],
                "properties": {
                    "weight": {"type": "number", "description": "Weight in kg"},
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
            description="Log sleep duration and optional quality score.",
            category="health",
            handler=log_sleep,
            input_schema={
                "type": "object",
                "required": ["hours"],
                "properties": {
                    "hours": {"type": "number", "description": "Hours of sleep"},
                    "quality": {"type": "number", "description": "Quality 1-10"},
                    "note": {"type": "string"},
                },
            },
            tags=["health", "sleep"],
        )
    )

    registry.register(
        ToolDefinition(
            name="log_mood",
            description="Log current mood (1-10 scale).",
            category="health",
            handler=log_mood,
            input_schema={
                "type": "object",
                "required": ["score"],
                "properties": {
                    "score": {"type": "number", "description": "Mood 1-10"},
                    "note": {"type": "string"},
                },
            },
            tags=["health", "mood"],
        )
    )

    registry.register(
        ToolDefinition(
            name="log_set",
            description=(
                "Log a single exercise set with weight and reps. "
                "Automatically tracks personal records (PR). "
                "Use for strength training: bench press, pullups, rows, etc."
            ),
            category="health",
            handler=log_set,
            input_schema={
                "type": "object",
                "required": ["exercise"],
                "properties": {
                    "exercise": {
                        "type": "string",
                        "description": "Exercise name (e.g. bench_press, pullups, cable_row)",
                    },
                    "weight": {
                        "type": "number",
                        "description": "Weight in kg (0 for bodyweight exercises)",
                    },
                    "reps": {
                        "type": "integer",
                        "description": "Number of repetitions",
                    },
                    "set_num": {
                        "type": "integer",
                        "description": "Set number (auto if 0)",
                    },
                    "note": {"type": "string"},
                },
            },
            tags=["health", "exercise", "training"],
        )
    )

    registry.register(
        ToolDefinition(
            name="get_pr",
            description=(
                "Get personal records (PR) for exercises. "
                "Without arguments — all PRs. With exercise name — PR for that exercise."
            ),
            category="health",
            handler=get_pr,
            input_schema={
                "type": "object",
                "properties": {
                    "exercise": {
                        "type": "string",
                        "description": "Exercise name (empty = all PRs)",
                    },
                },
            },
            tags=["health", "exercise", "pr"],
        )
    )

    registry.register(
        ToolDefinition(
            name="log_exercise",
            description="Log general exercise session (running, cycling, gym, etc.).",
            category="health",
            handler=log_exercise,
            input_schema={
                "type": "object",
                "required": ["exercise_type", "duration_min"],
                "properties": {
                    "exercise_type": {"type": "string", "description": "Type of exercise"},
                    "duration_min": {"type": "number", "description": "Duration in minutes"},
                    "calories": {"type": "number"},
                    "note": {"type": "string"},
                },
            },
            tags=["health", "exercise"],
        )
    )

    registry.register(
        ToolDefinition(
            name="log_water",
            description="Log water intake (glasses or ml).",
            category="health",
            handler=log_water,
            input_schema={
                "type": "object",
                "properties": {
                    "glasses": {"type": "number", "description": "Glasses (250ml each)"},
                    "ml": {"type": "number", "description": "Exact ml"},
                },
            },
            tags=["health", "water"],
        )
    )

    registry.register(
        ToolDefinition(
            name="health_report",
            description=(
                "Health and training report for last N days. "
                "Includes: weight trend, sleep, mood, training volume, new PRs."
            ),
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
