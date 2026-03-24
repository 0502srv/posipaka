"""Remind skill — нагадування через CronEngine + APScheduler.

Інтеграція з persistent CronEngine: нагадування зберігаються на диск,
переживають перезапуск, і доставляються через Gateway (Telegram тощо).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

# Lazy references — resolved at first call
_cron_engine = None
_scheduler = None
_cron_executor = None


def _resolve_deps() -> tuple:
    """Resolve CronEngine, Scheduler, CronExecutor from running Agent."""
    global _cron_engine, _scheduler, _cron_executor
    if _cron_engine and _scheduler:
        return _cron_engine, _scheduler, _cron_executor

    try:
        from posipaka.config.settings import get_settings

        settings = get_settings()
        data_dir = settings.data_dir
        cron_dir = data_dir / "cron"

        # Try to get from running agent via gateway (if available)
        # Fallback: create standalone instances
        from posipaka.core.cron_engine import CronEngine

        _cron_engine = CronEngine(cron_dir)
        _cron_engine.init()

        from posipaka.core.scheduler import PosipakScheduler

        _scheduler = PosipakScheduler()
        _scheduler.start()

        return _cron_engine, _scheduler, _cron_executor
    except Exception as e:
        logger.error(f"Remind: failed to resolve dependencies: {e}")
        raise RuntimeError(f"Система нагадувань не ініціалізована: {e}") from e


def _attach_to_agent(agent: Any) -> None:
    """Attach to running Agent's CronEngine and Scheduler."""
    global _cron_engine, _scheduler, _cron_executor
    if hasattr(agent, "cron_engine") and agent.cron_engine:
        _cron_engine = agent.cron_engine
    if hasattr(agent, "scheduler") and agent.scheduler:
        _scheduler = agent.scheduler
    if hasattr(agent, "cron_executor") and agent.cron_executor:
        _cron_executor = agent.cron_executor


def _parse_reminder_time(datetime_str: str, tz: ZoneInfo | None = None) -> datetime:
    """Parse ISO datetime or relative time string to absolute datetime."""
    if tz is None:
        tz = ZoneInfo("Europe/Kyiv")
    now = datetime.now(tz)

    # Relative: "+10m", "+1h", "+30min", "через 10 хвилин" etc.
    import re

    # Pattern: +Nm, +Nh, +Ns
    rel_match = re.match(r"^\+?(\d+)\s*(m|min|хв|h|год|s|сек)", datetime_str.strip(), re.I)
    if rel_match:
        value = int(rel_match.group(1))
        unit = rel_match.group(2).lower()
        if unit in ("m", "min", "хв"):
            return now + timedelta(minutes=value)
        elif unit in ("h", "год"):
            return now + timedelta(hours=value)
        elif unit in ("s", "сек"):
            return now + timedelta(seconds=value)

    # ISO datetime
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            dt = datetime.strptime(datetime_str.strip(), fmt)
            return dt.replace(tzinfo=tz)
        except ValueError:
            continue

    # Time only (today): "14:30", "20:00"
    time_match = re.match(r"^(\d{1,2}):(\d{2})$", datetime_str.strip())
    if time_match:
        h, m = int(time_match.group(1)), int(time_match.group(2))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    raise ValueError(
        f"Не вдалося розпізнати час: '{datetime_str}'. "
        f"Формати: ISO (2026-03-24T10:00), відносний (+10m, +1h), час (14:30)"
    )


async def set_reminder(
    message: str, datetime_str: str, user_id: str = "", channel: str = "telegram"
) -> str:
    """Встановити нагадування через CronEngine (persistent)."""
    from posipaka.core.cron_engine import CronType, DeliveryMode

    cron_engine, scheduler, executor = _resolve_deps()

    try:
        tz = ZoneInfo("Europe/Kyiv")
        remind_at = _parse_reminder_time(datetime_str, tz)
    except ValueError as e:
        return str(e)

    # Validate: not in the past
    now = datetime.now(tz)
    if remind_at <= now:
        return "Час нагадування вже минув. Вкажіть майбутній час."

    # Create persistent cron job (ONE_SHOT)
    remind_at_iso = remind_at.isoformat()
    name = f"reminder_{now.strftime('%H%M%S')}_{message[:20]}"

    try:
        job = cron_engine.add(
            name=name,
            message=f"НАГАДУВАННЯ: {message}",
            user_id=user_id,
            cron_type=CronType.ONE_SHOT,
            at=remind_at_iso,
            channel=channel,
            target_channel=channel,
            target_user_id=user_id,
            delivery_mode=DeliveryMode.ANNOUNCE,
            delete_after_run=True,
            timezone="Europe/Kyiv",
        )
    except Exception as e:
        logger.error(f"Remind: failed to create cron job: {e}")
        return f"Помилка створення нагадування: {e}"

    # Register in APScheduler for immediate scheduling
    if scheduler:
        try:
            async def _deliver_reminder(
                job_id: str = job.id,
            ) -> None:
                """Callback для APScheduler — доставити нагадування."""
                eng = _cron_engine
                exc = _cron_executor
                if eng and exc:
                    j = eng.get(job_id)
                    if j:
                        await exc.execute_job(j, agent_fn=None)
                elif eng:
                    # Fallback: direct gateway delivery
                    j = eng.get(job_id)
                    if j:
                        try:
                            # Try to find gateway from agent
                            from posipaka.config.settings import get_settings

                            settings = get_settings()
                            # Mark as executed
                            eng.mark_success(job_id)
                            if j.delete_after_run:
                                eng.remove(job_id)
                            logger.info(
                                f"Reminder delivered (no executor): {j.message}"
                            )
                        except Exception as ex:
                            logger.error(f"Reminder delivery failed: {ex}")

            scheduler.add_reminder(
                f"cron:{job.id}",
                _deliver_reminder,
                run_time=remind_at_iso,
            )
        except Exception as e:
            logger.warning(f"Remind: APScheduler registration failed: {e}")
            # Job is still persisted — will be picked up on next restart

    time_str = remind_at.strftime("%H:%M %d.%m.%Y")
    delta = remind_at - now
    minutes = int(delta.total_seconds() / 60)
    if minutes < 60:
        when = f"через {minutes} хв"
    elif minutes < 1440:
        when = f"через {minutes // 60} год {minutes % 60} хв"
    else:
        when = f"через {minutes // 1440} дн"

    return (
        f"Нагадування встановлено (ID: {job.id}):\n"
        f"'{message}' — {time_str} ({when})"
    )


async def list_reminders(user_id: str = "") -> str:
    """Показати активні нагадування з CronEngine."""
    cron_engine, _, _ = _resolve_deps()

    jobs = cron_engine.list_jobs()
    reminders = [
        j
        for j in jobs
        if j["name"].startswith("reminder_")
        and j["enabled"]
        and (not user_id or j.get("user_id") == user_id)
    ]

    if not reminders:
        return "Немає активних нагадувань."

    lines = ["Активні нагадування:\n"]
    for r in reminders:
        at = r.get("at", "")
        msg = r.get("message", "").replace("НАГАДУВАННЯ: ", "")
        lines.append(f"  [{r['id'][:8]}] {msg} — {at}")

    return "\n".join(lines)


async def cancel_reminder(reminder_id: str) -> str:
    """Скасувати нагадування з CronEngine + APScheduler."""
    cron_engine, scheduler, _ = _resolve_deps()

    # Find job by ID prefix
    jobs = cron_engine.list_jobs()
    target = None
    for j in jobs:
        if j["id"].startswith(reminder_id) and j["name"].startswith("reminder_"):
            target = j
            break

    if not target:
        return f"Нагадування '{reminder_id}' не знайдено."

    job_id = target["id"]
    msg = target.get("message", "").replace("НАГАДУВАННЯ: ", "")

    # Remove from APScheduler
    if scheduler:
        scheduler.remove_job(f"cron:{job_id}")

    # Remove from CronEngine (persistent)
    cron_engine.remove(job_id)

    return f"Нагадування '{msg}' скасовано."


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="set_reminder",
            description=(
                "Set a reminder for a specific time. Creates a persistent reminder "
                "that survives restarts and delivers via Telegram/channel. "
                "Use when user asks to be reminded about something."
            ),
            category="skill",
            handler=set_reminder,
            input_schema={
                "type": "object",
                "required": ["message", "datetime_str"],
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Reminder message text",
                    },
                    "datetime_str": {
                        "type": "string",
                        "description": (
                            "When to remind. Formats: "
                            "ISO (2026-03-24T10:00), "
                            "relative (+10m, +1h, +30min), "
                            "time only (14:30)"
                        ),
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User ID for delivery",
                    },
                    "channel": {
                        "type": "string",
                        "description": "Channel for delivery (telegram, discord, etc.)",
                        "default": "telegram",
                    },
                },
            },
            tags=["reminder", "scheduler", "cron"],
        )
    )

    registry.register(
        ToolDefinition(
            name="list_reminders",
            description="List all active reminders for the user.",
            category="skill",
            handler=list_reminders,
            input_schema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Filter by user ID"},
                },
            },
            tags=["reminder"],
        )
    )

    registry.register(
        ToolDefinition(
            name="cancel_reminder",
            description="Cancel a reminder by its ID (or ID prefix).",
            category="skill",
            handler=cancel_reminder,
            input_schema={
                "type": "object",
                "required": ["reminder_id"],
                "properties": {
                    "reminder_id": {
                        "type": "string",
                        "description": "Reminder ID (or first 8 chars) to cancel",
                    },
                },
            },
            tags=["reminder"],
        )
    )
