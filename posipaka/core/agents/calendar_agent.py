"""CalendarAgent — керування календарем та email."""

from __future__ import annotations

from loguru import logger

from posipaka.core.agents.base import AgentTask, BaseSpecializedAgent


class CalendarAgent(BaseSpecializedAgent):
    """Агент для роботи з календарем та поштою."""

    @property
    def name(self) -> str:
        return "calendar"

    @property
    def description(self) -> str:
        return "Manage calendar events and email (Gmail + Google Calendar)"

    @property
    def capabilities(self) -> list[str]:
        return [
            "calendar",
            "event",
            "meeting",
            "schedule",
            "email",
            "gmail",
            "mail",
            "letter",
            "календар",
            "подія",
            "зустріч",
            "розклад",
            "пошта",
            "лист",
            "імейл",
        ]

    async def execute(self, task: AgentTask) -> str:
        try:
            lower = task.description.lower()

            if any(w in lower for w in ("email", "mail", "лист", "пошт", "імейл")):
                from posipaka.integrations.gmail.tools import gmail_list

                return await gmail_list(max_results=5)

            if any(w in lower for w in ("calendar", "event", "календар", "подія", "розклад")):
                from posipaka.integrations.calendar.tools import calendar_list

                return await calendar_list(days_ahead=7)

            return f"CalendarAgent: не зрозумів запит — {task.description}"
        except Exception as e:
            logger.error(f"CalendarAgent error: {e}")
            return f"Помилка CalendarAgent: {e}"
