"""BaseChannel — абстракція для каналів месенджерів."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posipaka.core.agent import Agent


class BaseChannel(ABC):
    """Базовий клас для всіх каналів."""

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    @abstractmethod
    async def start(self) -> None:
        """Запустити канал."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Зупинити канал."""
        ...

    @abstractmethod
    async def send_message(self, user_id: str, text: str) -> None:
        """Надіслати повідомлення користувачу."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Ім'я каналу."""
        ...
