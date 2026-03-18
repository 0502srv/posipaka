"""Proactive Agent — Trigger System (секція 39 MASTER.md)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum

from loguru import logger


class TriggerType(StrEnum):
    SCHEDULE = "schedule"
    EVENT = "event"
    CONDITION = "condition"
    PATTERN = "pattern"
    WEBHOOK = "webhook"


@dataclass
class Trigger:
    id: str
    type: TriggerType
    config: dict
    action: str  # що зробити (природня мова)
    user_id: str
    channel: str = "telegram"
    cooldown_minutes: int = 60
    enabled: bool = True
    last_fired: float = 0.0


class TriggerManager:
    """
    Менеджер тригерів для проактивної поведінки агента.

    Вбудовані сценарії:
        - Email Monitor (кожні 15 хв)
        - Meeting Prep (за 30 хв до зустрічі)
        - Weekly Review (п'ятниця 18:00)
        - Deadline Watcher (щоранку)
    """

    def __init__(self) -> None:
        self._triggers: dict[str, Trigger] = {}

    def add(self, trigger: Trigger) -> None:
        self._triggers[trigger.id] = trigger
        logger.debug(f"Trigger added: {trigger.id} ({trigger.type})")

    def remove(self, trigger_id: str) -> bool:
        return self._triggers.pop(trigger_id, None) is not None

    def get(self, trigger_id: str) -> Trigger | None:
        return self._triggers.get(trigger_id)

    def list_triggers(self) -> list[dict]:
        return [
            {
                "id": t.id,
                "type": t.type,
                "action": t.action,
                "enabled": t.enabled,
                "cooldown_minutes": t.cooldown_minutes,
            }
            for t in self._triggers.values()
        ]

    def should_fire(self, trigger_id: str) -> bool:
        """Перевірити чи тригер може спрацювати (cooldown)."""
        trigger = self._triggers.get(trigger_id)
        if not trigger or not trigger.enabled:
            return False
        elapsed = time.time() - trigger.last_fired
        return elapsed >= trigger.cooldown_minutes * 60

    def mark_fired(self, trigger_id: str) -> None:
        trigger = self._triggers.get(trigger_id)
        if trigger:
            trigger.last_fired = time.time()

    def setup_builtins(self, user_id: str, channel: str = "telegram") -> None:
        """Створити вбудовані тригери."""
        builtins = [
            Trigger(
                id="email_monitor",
                type=TriggerType.SCHEDULE,
                config={"cron": "*/15 * * * *"},
                action="Перевір нові листи. Якщо є важливі — повідом мене.",
                user_id=user_id,
                channel=channel,
                cooldown_minutes=15,
            ),
            Trigger(
                id="weekly_review",
                type=TriggerType.SCHEDULE,
                config={"cron": "0 18 * * 5"},
                action="Підсумуй мій тиждень: що зроблено, що заплановано на наступний.",
                user_id=user_id,
                channel=channel,
                cooldown_minutes=60 * 24 * 6,
            ),
            Trigger(
                id="morning_brief",
                type=TriggerType.SCHEDULE,
                config={"cron": "0 9 * * *"},
                action="Ранковий дайджест: календар на сьогодні, непрочитані листи, погода.",
                user_id=user_id,
                channel=channel,
                cooldown_minutes=60 * 23,
            ),
        ]
        for t in builtins:
            self.add(t)
