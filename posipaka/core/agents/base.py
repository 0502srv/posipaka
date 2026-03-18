"""BaseAgent — абстракція для спеціалізованих агентів."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AgentTask:
    """Завдання для спеціалізованого агента."""

    description: str
    context: dict = field(default_factory=dict)
    result: str = ""
    status: str = "pending"  # pending | running | completed | failed


class BaseSpecializedAgent(ABC):
    """Базовий клас для спеціалізованих агентів."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    def capabilities(self) -> list[str]:
        """Список можливостей для routing."""
        return []

    @abstractmethod
    async def execute(self, task: AgentTask) -> str:
        """Виконати завдання."""
        ...

    def can_handle(self, task_description: str) -> float:
        """Оцінити чи може агент обробити завдання (0.0-1.0)."""
        lower = task_description.lower()
        score = 0.0
        for cap in self.capabilities:
            if cap.lower() in lower:
                score = max(score, 0.7)
        return score
