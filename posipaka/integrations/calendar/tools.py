"""Posipaka — Google Calendar Integration."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any


async def calendar_list(days_ahead: int = 7, calendar_id: str = "primary") -> str:
    """Показати події на найближчі дні."""
    try:
        service = _get_calendar_service()
        if not service:
            return "Google Calendar не налаштовано. Запустіть `posipaka integrations setup gmail`."

        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=20,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

        if not events:
            return f"Немає подій на наступні {days_ahead} днів."

        from posipaka.security.injection import sanitize_external_content

        lines = [f"📅 Календар на {days_ahead} днів:\n"]
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            summary = sanitize_external_content(event.get("summary", "(без назви)"), "calendar")
            location = event.get("location", "")
            line = f"• {start[:16]} — {summary}"
            if location:
                loc = sanitize_external_content(location, "calendar")
                line += f" 📍 {loc}"
            lines.append(line)

        return "\n".join(lines)
    except Exception as e:
        return f"Помилка Calendar: {e}"


async def calendar_create(
    title: str, start: str, end: str, description: str = "", location: str = ""
) -> str:
    """Створити подію в календарі."""
    try:
        service = _get_calendar_service()
        if not service:
            return "Google Calendar не налаштовано."

        event = {
            "summary": title,
            "start": {"dateTime": start, "timeZone": "Europe/Kyiv"},
            "end": {"dateTime": end, "timeZone": "Europe/Kyiv"},
        }
        if description:
            event["description"] = description
        if location:
            event["location"] = location

        created = service.events().insert(calendarId="primary", body=event).execute()
        return f"Подію створено: {created.get('htmlLink', title)}"
    except Exception as e:
        return f"Помилка створення події: {e}"


async def delete_event(event_id: str) -> str:
    """Видалити подію (requires approval)."""
    try:
        service = _get_calendar_service()
        if not service:
            return "Google Calendar не налаштовано."
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return f"Подію {event_id} видалено."
    except Exception as e:
        return f"Помилка видалення: {e}"


async def calendar_free_slots(date: str, duration_minutes: int = 60) -> str:
    """Знайти вільні слоти на дату."""
    try:
        service = _get_calendar_service()
        if not service:
            return "Google Calendar не налаштовано."

        day_start = f"{date}T08:00:00"
        day_end = f"{date}T20:00:00"

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=day_start + "+02:00",
                timeMax=day_end + "+02:00",
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

        # Simple free slot calculation
        busy = []
        for event in events:
            start = event["start"].get("dateTime", "")
            end = event["end"].get("dateTime", "")
            if start and end:
                busy.append((start[11:16], end[11:16]))

        return f"Зайняті слоти на {date}: {busy}\n(Вільний час = проміжки між ними)"
    except Exception as e:
        return f"Помилка: {e}"


def _get_calendar_service():
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_path = os.environ.get("GOOGLE_TOKEN_PATH", "")
        if not token_path or not os.path.exists(token_path):
            return None
        creds = Credentials.from_authorized_user_file(token_path)
        return build("calendar", "v3", credentials=creds)
    except ImportError:
        return None
    except Exception:
        return None


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="calendar_list",
            description="List upcoming calendar events.",
            category="integration",
            handler=calendar_list,
            input_schema={
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "Days to look ahead (default 7)",
                    },
                },
            },
            tags=["calendar", "google"],
        )
    )

    registry.register(
        ToolDefinition(
            name="calendar_create",
            description="Create a new calendar event. Requires approval.",
            category="integration",
            handler=calendar_create,
            input_schema={
                "type": "object",
                "required": ["title", "start", "end"],
                "properties": {
                    "title": {"type": "string"},
                    "start": {
                        "type": "string",
                        "description": "ISO datetime e.g. 2026-03-20T10:00:00",
                    },
                    "end": {"type": "string", "description": "ISO datetime"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                },
            },
            requires_approval=True,
            tags=["calendar", "google"],
        )
    )

    registry.register(
        ToolDefinition(
            name="delete_event",
            description="Delete a calendar event. Requires approval.",
            category="integration",
            handler=delete_event,
            input_schema={
                "type": "object",
                "required": ["event_id"],
                "properties": {
                    "event_id": {"type": "string", "description": "Event ID to delete"},
                },
            },
            requires_approval=True,
            tags=["calendar", "google"],
        )
    )
