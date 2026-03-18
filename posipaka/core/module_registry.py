"""ModuleRegistry — модульна архітектура / plugin system."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# ModuleType
# ---------------------------------------------------------------------------


class ModuleType(StrEnum):
    """Типи модулів системи."""

    CHANNEL = "channel"
    INTEGRATION = "integration"
    MEMORY = "memory"
    VOICE = "voice"
    SECURITY = "security"
    SKILL = "skill"
    CORE = "core"


# ---------------------------------------------------------------------------
# ModuleInfo
# ---------------------------------------------------------------------------


@dataclass
class ModuleInfo:
    """Метадані модуля."""

    name: str
    module_type: ModuleType
    version: str
    description: str
    author: str = ""
    dependencies: list[str] = field(default_factory=list)
    enabled: bool = True


# ---------------------------------------------------------------------------
# BaseModule ABC
# ---------------------------------------------------------------------------


class BaseModule(ABC):
    """Базовий клас для всіх модулів Posipaka."""

    @property
    @abstractmethod
    def info(self) -> ModuleInfo:
        """Метадані модуля."""
        ...

    async def initialize(self) -> None:  # noqa: B027
        """Ініціалізація модуля. Override у підкласах."""

    async def shutdown(self) -> None:  # noqa: B027
        """Зупинка модуля. Override у підкласах."""

    async def health_check(self) -> bool:
        """Перевірка стану модуля. За замовчуванням — True."""
        return True

    @property
    def enabled(self) -> bool:
        return self.info.enabled

    def enable(self) -> None:
        self.info.enabled = True
        logger.info(f"Module enabled: {self.info.name}")

    def disable(self) -> None:
        self.info.enabled = False
        logger.info(f"Module disabled: {self.info.name}")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ModuleLookupError(Exception):
    """Module not found in registry."""


class ModuleDependencyError(Exception):
    pass


# ---------------------------------------------------------------------------
# EventBus — inter-module communication
# ---------------------------------------------------------------------------


class EventBus:
    """Pub/sub шина подій для комунікації між модулями."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event: str, callback: Callable) -> None:
        """Підписатися на подію."""
        self._subscribers[event].append(callback)
        logger.debug(f"EventBus: subscribed to '{event}' ({callback.__qualname__})")

    def unsubscribe(self, event: str, callback: Callable) -> None:
        """Відписатися від події."""
        handlers = self._subscribers.get(event, [])
        if callback in handlers:
            handlers.remove(callback)

    async def publish(self, event: str, data: dict[str, Any] | None = None) -> None:
        """Опублікувати подію. Error isolation — один subscriber не ламає інших."""
        subscribers = self._subscribers.get(event, [])
        if not subscribers:
            return
        payload = data or {}
        for callback in subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(payload)
                else:
                    callback(payload)
            except Exception as e:
                logger.error(f"EventBus error [{event}] in {callback.__qualname__}: {e}")

    def list_events(self) -> dict[str, int]:
        """Кількість subscribers per event."""
        return {event: len(cbs) for event, cbs in self._subscribers.items() if cbs}


# ---------------------------------------------------------------------------
# ModuleRegistry
# ---------------------------------------------------------------------------


class ModuleRegistry:
    """Центральний реєстр модулів Posipaka."""

    def __init__(self) -> None:
        self._modules: dict[str, BaseModule] = {}
        self.event_bus = EventBus()

    # -- Registration -------------------------------------------------------

    def register(self, module: BaseModule) -> None:
        """Зареєструвати модуль."""
        name = module.info.name
        # Перевірка залежностей
        missing = [dep for dep in module.info.dependencies if dep not in self._modules]
        if missing:
            raise ModuleDependencyError(f"Module '{name}' requires missing dependencies: {missing}")
        if name in self._modules:
            logger.warning(f"Module '{name}' already registered, overwriting")
        self._modules[name] = module
        logger.info(f"Registered module: {name} [{module.info.module_type}] v{module.info.version}")

    def unregister(self, name: str) -> None:
        """Видалити модуль з реєстру."""
        if name not in self._modules:
            raise ModuleLookupError(f"Module '{name}' not found")
        # Перевірка — чи є модулі, що залежать від цього
        dependents = [
            m.info.name
            for m in self._modules.values()
            if name in m.info.dependencies and m.info.name != name
        ]
        if dependents:
            logger.warning(f"Unregistering '{name}' which is depended on by: {dependents}")
        del self._modules[name]
        logger.info(f"Unregistered module: {name}")

    # -- Lookup -------------------------------------------------------------

    def get(self, name: str) -> BaseModule | None:
        """Отримати модуль за ім'ям."""
        return self._modules.get(name)

    def list_modules(self, module_type: ModuleType | None = None) -> list[ModuleInfo]:
        """Список модулів, опціонально фільтр по типу."""
        modules = self._modules.values()
        if module_type is not None:
            modules = [m for m in modules if m.info.module_type == module_type]
        return [m.info for m in modules]

    def get_enabled(self) -> list[BaseModule]:
        """Список увімкнених модулів."""
        return [m for m in self._modules.values() if m.enabled]

    # -- Enable / Disable ---------------------------------------------------

    def enable_module(self, name: str) -> bool:
        """Увімкнути модуль. Повертає True якщо знайдено."""
        module = self._modules.get(name)
        if module is None:
            return False
        module.enable()
        return True

    def disable_module(self, name: str) -> bool:
        """Вимкнути модуль. Повертає True якщо знайдено."""
        module = self._modules.get(name)
        if module is None:
            return False
        module.disable()
        return True

    # -- Lifecycle ----------------------------------------------------------

    async def initialize_all(self) -> dict[str, bool]:
        """Ініціалізувати всі увімкнені модулі. Повертає {name: success}."""
        results: dict[str, bool] = {}
        # Ініціалізація у порядку залежностей (topological sort)
        ordered = self._topological_order()
        for name in ordered:
            module = self._modules[name]
            if not module.enabled:
                results[name] = True
                continue
            try:
                await module.initialize()
                results[name] = True
                logger.info(f"Module initialized: {name}")
                await self.event_bus.publish("module.initialized", {"module": name})
            except Exception as e:
                results[name] = False
                logger.error(f"Module init failed [{name}]: {e}")
                await self.event_bus.publish(
                    "module.init_failed", {"module": name, "error": str(e)}
                )
        return results

    async def shutdown_all(self) -> None:
        """Зупинити всі модулі (зворотній порядок залежностей)."""
        ordered = self._topological_order()
        for name in reversed(ordered):
            module = self._modules[name]
            try:
                await module.shutdown()
                logger.info(f"Module shutdown: {name}")
            except Exception as e:
                logger.error(f"Module shutdown failed [{name}]: {e}")

    async def health_check_all(self) -> dict[str, bool]:
        """Health check усіх увімкнених модулів."""
        results: dict[str, bool] = {}
        for name, module in self._modules.items():
            if not module.enabled:
                results[name] = True
                continue
            try:
                results[name] = await module.health_check()
            except Exception as e:
                results[name] = False
                logger.error(f"Health check failed [{name}]: {e}")
        return results

    # -- Internal -----------------------------------------------------------

    def _topological_order(self) -> list[str]:
        """Топологічне сортування модулів за залежностями."""
        visited: set[str] = set()
        order: list[str] = []

        def visit(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            module = self._modules.get(name)
            if module is None:
                return
            for dep in module.info.dependencies:
                if dep in self._modules:
                    visit(dep)
            order.append(name)

        for name in self._modules:
            visit(name)
        return order
