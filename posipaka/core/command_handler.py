"""CommandRouter — обробка /команд агента."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger


class CommandRouter:
    """Реєстрація та виконання /команд."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[..., Coroutine[Any, Any, str]]] = {}
        self._aliases: dict[str, str] = {}

    def register(
        self,
        name: str,
        handler: Callable[..., Coroutine[Any, Any, str]],
        aliases: list[str] | None = None,
    ) -> None:
        """Зареєструвати обробник команди."""
        self._handlers[name] = handler
        for alias in aliases or []:
            self._aliases[alias] = name

    async def execute(self, command: str, args: str, user_id: str) -> str:
        """Виконати команду. Повертає результат або повідомлення про помилку."""
        resolved = self._aliases.get(command, command)
        handler = self._handlers.get(resolved)
        if not handler:
            return f"Невідома команда: /{command}"
        try:
            return await handler(args, user_id)
        except Exception as e:
            logger.error(f"Command /{command} error: {e}")
            return f"Помилка при виконанні /{command}: {e}"

    def list_commands(self) -> list[str]:
        """Список всіх зареєстрованих команд."""
        return sorted(self._handlers.keys())
