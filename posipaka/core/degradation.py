"""Graceful degradation manager — керування поведінкою при збоях компонентів."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Any

from loguru import logger


class SystemMode(StrEnum):
    FULL = "full"           # Всі системи працюють
    DEGRADED = "degraded"   # Деякі некритичні системи недоступні
    MINIMAL = "minimal"     # Тільки базова функціональність
    EMERGENCY = "emergency" # Read-only, без виконання інструментів


@dataclass
class ComponentStatus:
    name: str
    healthy: bool = True
    last_check: float = 0.0
    failures: int = 0
    last_error: str = ""


class DegradationManager:
    """
    Керує деградацією системи при збоях компонентів.

    Матриця фолбеків:
    - LLM недоступний -> cached responses + повідомлення користувачу
    - SQLite недоступний -> RAM-only memory (без persistence)
    - ChromaDB недоступний -> BM25-only search (Tantivy)
    - Tantivy недоступний -> SQLite LIKE search
    - Мережа недоступна -> тільки локальні інструменти
    - Диск повний -> read-only режим, cleanup prompt
    """

    FALLBACK_MATRIX: dict[str, dict[str, Any]] = {
        "llm": {
            "degraded_msg": "LLM тимчасово недоступний. Використовую кешовані відповіді.",
            "fallback": "semantic_cache",
            "mode_threshold": SystemMode.DEGRADED,
        },
        "sqlite": {
            "degraded_msg": "База даних недоступна. Використовую оперативну пам'ять.",
            "fallback": "ram_memory",
            "mode_threshold": SystemMode.DEGRADED,
        },
        "chromadb": {
            "degraded_msg": "Векторний пошук недоступний. Використовую текстовий пошук.",
            "fallback": "tantivy_search",
            "mode_threshold": SystemMode.DEGRADED,
        },
        "tantivy": {
            "degraded_msg": "Повнотекстовий пошук недоступний. Використовую базовий пошук.",
            "fallback": "sqlite_like",
            "mode_threshold": SystemMode.DEGRADED,
        },
        "network": {
            "degraded_msg": "Мережа недоступна. Тільки локальні інструменти.",
            "fallback": "local_only",
            "mode_threshold": SystemMode.DEGRADED,
        },
        "disk": {
            "degraded_msg": "Критично мало місця на диску. Read-only режим.",
            "fallback": "read_only",
            "mode_threshold": SystemMode.EMERGENCY,
        },
    }

    def __init__(self) -> None:
        self._components: dict[str, ComponentStatus] = {}
        self._mode = SystemMode.FULL
        self._mode_override: SystemMode | None = None
        self._listeners: list[Callable] = []

    @property
    def mode(self) -> SystemMode:
        return self._mode_override or self._mode

    def register_component(self, name: str) -> None:
        """Зареєструвати компонент для моніторингу."""
        self._components[name] = ComponentStatus(name=name)

    def on_mode_change(self, callback: Callable) -> None:
        """Додати listener на зміну режиму системи."""
        self._listeners.append(callback)

    def report_failure(self, component: str, error: str = "") -> None:
        """Повідомити про збій компонента."""
        status = self._components.get(component)
        if not status:
            self.register_component(component)
            status = self._components[component]

        status.healthy = False
        status.failures += 1
        status.last_error = error
        status.last_check = time.time()

        logger.warning(f"Збій компонента: {component} (#{status.failures}): {error}")
        self._recalculate_mode()

    def report_recovery(self, component: str) -> None:
        """Повідомити про відновлення компонента."""
        status = self._components.get(component)
        if status:
            status.healthy = True
            status.failures = 0
            status.last_error = ""
            status.last_check = time.time()
            logger.info(f"Компонент відновлено: {component}")
            self._recalculate_mode()

    def get_fallback(self, component: str) -> str | None:
        """Отримати стратегію фолбеку для компонента."""
        if component in self.FALLBACK_MATRIX:
            return self.FALLBACK_MATRIX[component]["fallback"]
        return None

    def get_degraded_message(self, component: str) -> str:
        """Отримати повідомлення для користувача при деградації компонента."""
        if component in self.FALLBACK_MATRIX:
            return self.FALLBACK_MATRIX[component]["degraded_msg"]
        return f"Компонент {component} тимчасово недоступний."

    def check_system_health(self) -> dict:
        """Повний звіт про стан системи."""
        return {
            "mode": self.mode.value,
            "components": {
                name: {
                    "healthy": s.healthy,
                    "failures": s.failures,
                    "last_error": s.last_error,
                }
                for name, s in self._components.items()
            },
        }

    def _recalculate_mode(self) -> None:
        """Перерахувати режим системи на основі стану компонентів."""
        old_mode = self._mode
        failed = [
            name for name, s in self._components.items() if not s.healthy
        ]

        if not failed:
            self._mode = SystemMode.FULL
        elif any(
            self.FALLBACK_MATRIX.get(f, {}).get("mode_threshold") == SystemMode.EMERGENCY
            for f in failed
        ):
            self._mode = SystemMode.EMERGENCY
        elif "llm" in failed and "sqlite" in failed:
            self._mode = SystemMode.MINIMAL
        else:
            self._mode = SystemMode.DEGRADED

        if old_mode != self._mode:
            logger.warning(f"Зміна режиму системи: {old_mode.value} -> {self._mode.value}")
            for listener in self._listeners:
                try:
                    listener(old_mode, self._mode)
                except Exception as e:
                    logger.error(f"Помилка listener зміни режиму: {e}")


async def run_in_mode(
    degradation: DegradationManager,
    component: str,
    primary: Callable,
    fallback: Callable | None = None,
    **kwargs,
) -> Any:
    """
    Виконати з автоматичним фолбеком при збої.

    Використання:
        result = await run_in_mode(
            degradation, "llm",
            primary=lambda: llm.complete(...),
            fallback=lambda: semantic_cache.get(...),
        )
    """
    try:
        result = await primary(**kwargs) if asyncio.iscoroutinefunction(primary) else primary(**kwargs)
        degradation.report_recovery(component)
        return result
    except Exception as e:
        degradation.report_failure(component, str(e))
        if fallback:
            logger.info(f"Використовую фолбек для {component}")
            try:
                return await fallback(**kwargs) if asyncio.iscoroutinefunction(fallback) else fallback(**kwargs)
            except Exception as fe:
                logger.error(f"Фолбек для {component} також не спрацював: {fe}")
                raise
        raise
