"""Send notifications, manage digests and reminders."""

from __future__ import annotations

from loguru import logger

from posipaka.core.agents.base import AgentTask, BaseSpecializedAgent


class NotificationAgent(BaseSpecializedAgent):
    @property
    def name(self) -> str:
        return "notification"

    @property
    def description(self) -> str:
        return "Send notifications, manage digests and reminders"

    @property
    def capabilities(self) -> list[str]:
        return [
            "notify",
            "alert",
            "send",
            "digest",
            "notification",
            "сповістити",
            "нагадати",
            "дайджест",
            "сповіщення",
        ]

    async def execute(self, task: AgentTask) -> str:
        try:
            desc = task.description.lower()

            if "digest" in desc or "дайджест" in desc:
                from posipaka.skills.builtin.digest.tools import create_digest

                return await create_digest()

            if "remind" in desc or "нагад" in desc:
                from posipaka.skills.builtin.remind.tools import list_reminders

                return await list_reminders()

            return f"Сповіщення: {task.description}"

        except Exception as e:
            logger.error(f"NotificationAgent error: {e}")
            return f"Помилка NotificationAgent: {e}"
