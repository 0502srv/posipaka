"""ModelRouter — розподіл моделей по задачах.

Підтримує три режими:
1. single   — одна модель для всього
2. auto     — автоматичний вибір по складності (simple/default/complex)
3. advanced — окрема модель для кожної категорії задач
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class ModelProfile:
    """Налаштування моделі для конкретної категорії."""

    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    description: str = ""


@dataclass
class ModelRouterConfig:
    """Повна конфігурація model routing.

    Режими:
    - single:   profiles["default"] для всього
    - auto:     profiles["simple"/"default"/"complex"] по складності
    - advanced: profiles per category (code/research/chat/tools/...)
    """

    mode: str = "auto"  # single | auto | advanced
    profiles: dict[str, ModelProfile] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "profiles": {
                k: {
                    "model": p.model,
                    "temperature": p.temperature,
                    "max_tokens": p.max_tokens,
                    "description": p.description,
                }
                for k, p in self.profiles.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelRouterConfig:
        profiles = {}
        for k, v in data.get("profiles", {}).items():
            profiles[k] = ModelProfile(
                model=v.get("model", ""),
                temperature=v.get("temperature", 0.7),
                max_tokens=v.get("max_tokens", 4096),
                description=v.get("description", ""),
            )
        return cls(mode=data.get("mode", "auto"), profiles=profiles)


# Категорії задач для advanced mode
TASK_CATEGORIES: dict[str, list[str]] = {
    "chat": [
        r"^(привіт|hello|hi|hey|дякую|thanks|bye|бувай)\b",
        r"^(як справи|how are you|що нового)",
    ],
    "code": [
        r"(код|code|скрипт|script|програм|python|javascript)",
        r"(debug|баг|помилка в коді|fix|refactor)",
        r"(github|git|commit|deploy|docker)",
    ],
    "research": [
        r"(дослідж|research|проаналізуй|analyze)",
        r"(що таке|who is|хто такий|розкажи про)",
        r"(порівняй|compare|versus|проти)",
    ],
    "writing": [
        r"(напиши|write|створи текст|draft|compose)",
        r"(лист|email|стаття|article|документ)",
        r"(переклади|translate|summarize|підсумуй)",
    ],
    "tools": [
        r"(погода|weather|calendar|пошта|gmail)",
        r"(нагадай|remind|timer|pomodoro)",
        r"(витрати|expense|income|finance|bookmark)",
    ],
    "reasoning": [
        r"(чому|why|explain|поясни|як працює)",
        r"(plan|план|strategy|стратегія|архітектур)",
        r"(math|математ|обчисли|calculate)",
    ],
}

# Mapping для auto mode
_SIMPLE_CATEGORIES = {"chat", "tools"}
_COMPLEX_CATEGORIES = {"code", "research", "reasoning", "writing"}


class ModelRouter:
    """Вибирає модель і параметри залежно від задачі.

    Три режими:
    - single:   одна модель для всіх запитів
    - auto:     simple/default/complex по складності
    - advanced: окрема модель per category
    """

    def __init__(
        self,
        default_model: str = "mistral-large-latest",
        fast_model: str = "mistral-small-latest",
        complex_model: str = "mistral-large-latest",
        config: ModelRouterConfig | None = None,
    ) -> None:
        if config:
            self._config = config
        else:
            # Сумісність: побудувати config з простих параметрів
            self._config = ModelRouterConfig(
                mode="auto",
                profiles={
                    "default": ModelProfile(
                        model=default_model,
                        max_tokens=2048,
                        description="Стандартні запити",
                    ),
                    "simple": ModelProfile(
                        model=fast_model,
                        temperature=0.4,
                        max_tokens=1024,
                        description="Прості запити (привіт, погода)",
                    ),
                    "complex": ModelProfile(
                        model=complex_model,
                        temperature=0.5,
                        max_tokens=2048,
                        description="Складні задачі (код, аналіз)",
                    ),
                },
            )

        # Compile patterns once
        self._compiled: dict[str, list[re.Pattern]] = {}
        for cat, patterns in TASK_CATEGORIES.items():
            self._compiled[cat] = [re.compile(p, re.I) for p in patterns]

    @property
    def config(self) -> ModelRouterConfig:
        return self._config

    @property
    def mode(self) -> str:
        return self._config.mode

    @property
    def default_model(self) -> str:
        p = self._config.profiles.get("default")
        return p.model if p else "mistral-large-latest"

    @property
    def fast_model(self) -> str:
        p = self._config.profiles.get("simple")
        return p.model if p else self.default_model

    @property
    def complex_model(self) -> str:
        p = self._config.profiles.get("complex")
        return p.model if p else self.default_model

    def select(self, message: str, tools_count: int = 0) -> str:
        """Вибрати модель. Повертає назву моделі."""
        profile = self.select_profile(message, tools_count)
        return profile.model

    def select_profile(
        self,
        message: str,
        tools_count: int = 0,
    ) -> ModelProfile:
        """Вибрати повний профіль (модель + settings)."""
        mode = self._config.mode
        profiles = self._config.profiles

        # Single mode — одна модель для всього
        if mode == "single":
            profile = profiles.get("default", ModelProfile(model="mistral-large-latest"))
            logger.debug(f"ModelRouter[single]: {profile.model}")
            return profile

        # Detect category
        category = self._detect_category(message)

        # Advanced mode — profile per category
        if mode == "advanced" and category in profiles:
            profile = profiles[category]
            logger.debug(f"ModelRouter[advanced]: {profile.model} ({category})")
            return profile

        # Auto mode — simple/default/complex
        if category in _SIMPLE_CATEGORIES:
            profile = profiles.get("simple", profiles.get("default"))
        elif category in _COMPLEX_CATEGORIES:
            profile = profiles.get("complex", profiles.get("default"))
        else:
            profile = profiles.get("default")

        # Fallback
        if not profile:
            profile = ModelProfile(model="mistral-large-latest")

        # Many tools = need smarter model
        if tools_count > 5 and "complex" in profiles:
            profile = profiles["complex"]

        logger.debug(f"ModelRouter[{mode}]: {profile.model} ({category})")
        return profile

    def _detect_category(self, message: str) -> str:
        """Визначити категорію запиту."""
        msg = message.strip()
        best_cat = "default"
        for cat, patterns in self._compiled.items():
            for pattern in patterns:
                if pattern.search(msg):
                    return cat
        return best_cat

    def get_categories(self) -> list[dict[str, str]]:
        """Список доступних категорій для UI."""
        return [
            {"key": "default", "name": "Стандартні запити"},
            {"key": "simple", "name": "Прості (привіт, погода, час)"},
            {"key": "complex", "name": "Складні (код, аналіз, дослідження)"},
            {"key": "chat", "name": "Чат / розмова"},
            {"key": "code", "name": "Код / програмування"},
            {"key": "research", "name": "Дослідження / аналіз"},
            {"key": "writing", "name": "Написання текстів"},
            {"key": "tools", "name": "Інструменти (погода, пошта)"},
            {"key": "reasoning", "name": "Логіка / пояснення"},
        ]
