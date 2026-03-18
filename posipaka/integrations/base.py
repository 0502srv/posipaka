"""BaseIntegration — базовий клас для інтеграцій."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseIntegration(ABC):
    """Базовий клас для інтеграцій."""

    @abstractmethod
    def register(self, registry: Any) -> None:
        """Зареєструвати tools в ToolRegistry."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Ім'я інтеграції."""
        ...

    @property
    def available(self) -> bool:
        """Чи доступна інтеграція (залежності, ключі)."""
        return True
