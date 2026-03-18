"""Public Extension API — стандартизований інтерфейс для розширень (Section 79)."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from loguru import logger


@dataclass
class ExtensionMetadata:
    """Метадані розширення."""

    name: str
    version: str
    author: str
    description: str = ""
    api_version: str = "1.0"


class ExtensionPoint(StrEnum):
    """Тип точки розширення."""

    TOOL = "tool"
    SKILL = "skill"
    CHANNEL = "channel"
    INTEGRATION = "integration"
    MIDDLEWARE = "middleware"
    HOOK = "hook"


class Extension(abc.ABC):
    """Базовий клас розширення — всі розширення наслідують цей ABC."""

    @property
    @abc.abstractmethod
    def metadata(self) -> ExtensionMetadata:
        """Метадані розширення."""

    @property
    @abc.abstractmethod
    def extension_point(self) -> ExtensionPoint:
        """Точка розширення, до якої належить це розширення."""

    @abc.abstractmethod
    async def install(self, agent: Any) -> None:
        """Встановити розширення в агента."""

    @abc.abstractmethod
    async def uninstall(self, agent: Any) -> None:
        """Видалити розширення з агента."""

    def validate(self) -> list[str]:
        """Валідація розширення. Повертає список помилок (порожній = ОК)."""
        errors: list[str] = []
        meta = self.metadata
        if not meta.name or not meta.name.strip():
            errors.append("Extension name is required")
        if not meta.version or not meta.version.strip():
            errors.append("Extension version is required")
        if not meta.author or not meta.author.strip():
            errors.append("Extension author is required")
        if meta.api_version != "1.0":
            errors.append(f"Unsupported api_version: {meta.api_version} (expected 1.0)")
        return errors


class ExtensionManager:
    """Менеджер розширень — реєстрація, встановлення, валідація."""

    def __init__(self) -> None:
        self._extensions: dict[str, Extension] = {}

    def register(self, extension: Extension) -> bool:
        """Зареєструвати розширення. Повертає True при успіху."""
        name = extension.metadata.name
        if name in self._extensions:
            logger.warning(f"Extension already registered: {name}")
            return False

        errors = extension.validate()
        if errors:
            logger.error(f"Extension {name} validation failed: {errors}")
            return False

        self._extensions[name] = extension
        logger.info(
            f"Registered extension: {name} v{extension.metadata.version} "
            f"({extension.extension_point})"
        )
        return True

    def unregister(self, name: str) -> bool:
        """Видалити розширення з реєстру. Повертає True при успіху."""
        if name not in self._extensions:
            logger.warning(f"Extension not found: {name}")
            return False

        del self._extensions[name]
        logger.info(f"Unregistered extension: {name}")
        return True

    def list_extensions(self) -> list[ExtensionMetadata]:
        """Повернути метадані всіх зареєстрованих розширень."""
        return [ext.metadata for ext in self._extensions.values()]

    async def install_all(self, agent: Any) -> dict[str, bool]:
        """Встановити всі зареєстровані розширення. Повертає {name: success}."""
        results: dict[str, bool] = {}
        for name, ext in self._extensions.items():
            try:
                await ext.install(agent)
                results[name] = True
                logger.info(f"Installed extension: {name}")
            except Exception as exc:
                results[name] = False
                logger.error(f"Failed to install extension {name}: {exc}")
        return results

    def validate_all(self) -> dict[str, list[str]]:
        """Валідувати всі розширення. Повертає {name: [errors]}."""
        results: dict[str, list[str]] = {}
        for name, ext in self._extensions.items():
            results[name] = ext.validate()
        return results
