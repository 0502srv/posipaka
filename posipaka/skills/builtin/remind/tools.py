"""Remind skill — нагадування через APScheduler."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

# In-memory store (replaced by APScheduler in full implementation)
_reminders: dict[str, dict] = {}


async def set_reminder(message: str, datetime_str: str, user_id: str = "") -> str:
    """Встановити нагадування."""
    reminder_id = str(uuid.uuid4())[:8]
    _reminders[reminder_id] = {
        "message": message,
        "datetime": datetime_str,
        "user_id": user_id,
        "created_at": datetime.now().isoformat(),
    }
    return f"Нагадування створено (ID: {reminder_id}): '{message}' на {datetime_str}"


async def list_reminders(user_id: str = "") -> str:
    """Показати активні нагадування."""
    if not _reminders:
        return "Немає активних нагадувань."

    lines = ["Активні нагадування:\n"]
    for rid, r in _reminders.items():
        if user_id and r.get("user_id") != user_id:
            continue
        lines.append(f"• [{rid}] {r['message']} — {r['datetime']}")

    return "\n".join(lines) if len(lines) > 1 else "Немає нагадувань для вас."


async def cancel_reminder(reminder_id: str) -> str:
    """Скасувати нагадування."""
    if reminder_id in _reminders:
        msg = _reminders.pop(reminder_id)["message"]
        return f"Нагадування '{msg}' скасовано."
    return f"Нагадування {reminder_id} не знайдено."


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="set_reminder",
            description=(
                "Set a reminder for a specific time."
                " Use when user asks to be reminded about something."
            ),
            category="skill",
            handler=set_reminder,
            input_schema={
                "type": "object",
                "required": ["message", "datetime_str"],
                "properties": {
                    "message": {"type": "string", "description": "Reminder message"},
                    "datetime_str": {
                        "type": "string",
                        "description": (
                            "When to remind (ISO datetime or relative like '2026-03-18T10:00')"
                        ),
                    },
                    "user_id": {"type": "string"},
                },
            },
            tags=["reminder", "scheduler"],
        )
    )

    registry.register(
        ToolDefinition(
            name="list_reminders",
            description="List all active reminders.",
            category="skill",
            handler=list_reminders,
            input_schema={
                "type": "object",
                "properties": {"user_id": {"type": "string"}},
            },
            tags=["reminder"],
        )
    )

    registry.register(
        ToolDefinition(
            name="cancel_reminder",
            description="Cancel a reminder by ID.",
            category="skill",
            handler=cancel_reminder,
            input_schema={
                "type": "object",
                "required": ["reminder_id"],
                "properties": {
                    "reminder_id": {"type": "string", "description": "Reminder ID to cancel"},
                },
            },
            tags=["reminder"],
        )
    )
