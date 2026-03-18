"""Chaos Engineering — контрольована ін'єкція збоїв (Section 80)."""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from loguru import logger


class FailureType(StrEnum):
    """Типи збоїв для ін'єкції."""

    LATENCY = "latency"
    ERROR = "error"
    TIMEOUT = "timeout"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    NETWORK_PARTITION = "network_partition"


@dataclass
class ChaosExperiment:
    """Опис хаос-експерименту."""

    name: str
    failure_type: FailureType
    target_component: str
    duration_seconds: float = 30.0
    probability: float = 0.5  # 0.0–1.0
    enabled: bool = True

    def __post_init__(self) -> None:
        self.probability = max(0.0, min(1.0, self.probability))


class ChaosEngine:
    """
    Рушій хаос-інженерії — безпечно ін'єктує збої для перевірки стійкості.

    УВАГА: _active=False за замовчуванням — ніколи не вмикається автоматично в продакшені.
    Використовуйте enable() тільки у тестових/staging середовищах.
    """

    # Параметри ін'єкції за типом збою
    _LATENCY_RANGE: tuple[float, float] = (0.5, 3.0)
    _TIMEOUT_DELAY: float = 30.0

    def __init__(self) -> None:
        self._experiments: dict[str, ChaosExperiment] = {}
        self._active: bool = False
        self._injection_log: list[dict[str, Any]] = []

    # ── Керування експериментами ──────────────────────────

    def add_experiment(self, exp: ChaosExperiment) -> None:
        """Додати хаос-експеримент."""
        self._experiments[exp.name] = exp
        logger.info(
            f"Chaos experiment added: {exp.name} "
            f"({exp.failure_type} → {exp.target_component}, p={exp.probability})"
        )

    def remove_experiment(self, name: str) -> None:
        """Видалити хаос-експеримент."""
        if name in self._experiments:
            del self._experiments[name]
            logger.info(f"Chaos experiment removed: {name}")
        else:
            logger.warning(f"Chaos experiment not found: {name}")

    # ── Активація / деактивація ───────────────────────────

    def enable(self) -> None:
        """Увімкнути chaos engine (тільки для тестування!)."""
        self._active = True
        logger.warning("Chaos engine ENABLED — failure injection is active")

    def disable(self) -> None:
        """Вимкнути chaos engine."""
        self._active = False
        logger.info("Chaos engine disabled")

    # ── Ін'єкція збоїв ───────────────────────────────────

    def should_inject(self, component: str) -> FailureType | None:
        """Перевірити, чи потрібно ін'єктувати збій для компонента."""
        if not self._active:
            return None

        for exp in self._experiments.values():
            if not exp.enabled:
                continue
            if exp.target_component != component:
                continue
            if random.random() < exp.probability:
                logger.debug(
                    f"Chaos: injecting {exp.failure_type} into {component} "
                    f"(experiment: {exp.name})"
                )
                return exp.failure_type

        return None

    async def inject_failure(self, failure_type: FailureType, component: str) -> None:
        """Ін'єктувати конкретний тип збою."""
        ts = time.time()
        self._injection_log.append(
            {
                "failure_type": str(failure_type),
                "component": component,
                "timestamp": ts,
            }
        )

        if failure_type == FailureType.LATENCY:
            delay = random.uniform(*self._LATENCY_RANGE)
            logger.warning(f"Chaos: adding {delay:.2f}s latency to {component}")
            await asyncio.sleep(delay)

        elif failure_type == FailureType.ERROR:
            logger.warning(f"Chaos: raising error in {component}")
            raise RuntimeError(f"Chaos injection: simulated error in {component}")

        elif failure_type == FailureType.TIMEOUT:
            logger.warning(f"Chaos: simulating timeout in {component}")
            await asyncio.sleep(self._TIMEOUT_DELAY)
            raise TimeoutError(f"Chaos injection: simulated timeout in {component}")

        elif failure_type == FailureType.RESOURCE_EXHAUSTION:
            logger.warning(f"Chaos: simulating resource exhaustion in {component}")
            raise MemoryError(
                f"Chaos injection: simulated resource exhaustion in {component}"
            )

        elif failure_type == FailureType.NETWORK_PARTITION:
            logger.warning(f"Chaos: simulating network partition for {component}")
            raise ConnectionError(
                f"Chaos injection: simulated network partition for {component}"
            )

    # ── Звіт ──────────────────────────────────────────────

    def get_report(self) -> dict[str, Any]:
        """Повернути звіт про хаос-експерименти та ін'єкції."""
        return {
            "active": self._active,
            "experiments": {
                name: {
                    "failure_type": str(exp.failure_type),
                    "target_component": exp.target_component,
                    "probability": exp.probability,
                    "duration_seconds": exp.duration_seconds,
                    "enabled": exp.enabled,
                }
                for name, exp in self._experiments.items()
            },
            "total_injections": len(self._injection_log),
            "recent_injections": self._injection_log[-10:],
        }
