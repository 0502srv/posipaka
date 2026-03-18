"""Response complexity levels.

Дозволяє користувачу обрати рівень складності відповідей:
- ELI5 (простий)
- STANDARD (за замовчуванням)
- TECHNICAL (для розробників)
- EXPERT (максимальна деталізація)
"""

from __future__ import annotations

from enum import StrEnum

from loguru import logger


class ComplexityLevel(StrEnum):
    ELI5 = "eli5"
    STANDARD = "standard"
    TECHNICAL = "technical"
    EXPERT = "expert"


# System prompt addons per level
_LEVEL_PROMPTS: dict[ComplexityLevel, str] = {
    ComplexityLevel.ELI5: (
        "RESPONSE STYLE: Explain everything in the simplest possible terms, "
        "as if to a 5-year-old. Use analogies, avoid jargon. "
        "Short sentences. No code unless explicitly asked."
    ),
    ComplexityLevel.STANDARD: "",  # Default — no addon
    ComplexityLevel.TECHNICAL: (
        "RESPONSE STYLE: Use technical terminology freely. "
        "Include code examples, architecture details, and implementation specifics. "
        "Assume the reader is a software developer."
    ),
    ComplexityLevel.EXPERT: (
        "RESPONSE STYLE: Maximum detail. Include edge cases, performance implications, "
        "security considerations, and trade-offs. Reference standards and best practices. "
        "Assume deep domain expertise."
    ),
}


class ComplexityManager:
    """Керує рівнем складності відповідей per-user."""

    def __init__(self) -> None:
        self._user_levels: dict[str, ComplexityLevel] = {}
        self._default = ComplexityLevel.STANDARD

    def set_level(self, user_id: str, level: str) -> bool:
        """Встановити рівень складності для користувача."""
        try:
            parsed = ComplexityLevel(level.lower())
            self._user_levels[user_id] = parsed
            logger.info(f"Complexity level for {user_id}: {parsed.value}")
            return True
        except ValueError:
            return False

    def get_level(self, user_id: str) -> ComplexityLevel:
        return self._user_levels.get(user_id, self._default)

    def get_system_prompt_addon(self, user_id: str) -> str:
        """Повернути addon для system prompt відповідно до рівня."""
        level = self.get_level(user_id)
        return _LEVEL_PROMPTS.get(level, "")

    def set_default(self, level: str) -> bool:
        try:
            self._default = ComplexityLevel(level.lower())
            return True
        except ValueError:
            return False

    @staticmethod
    def available_levels() -> list[str]:
        return [level.value for level in ComplexityLevel]

    def format_status(self, user_id: str) -> str:
        level = self.get_level(user_id)
        descriptions = {
            ComplexityLevel.ELI5: "Простий (як для 5-річного)",
            ComplexityLevel.STANDARD: "Стандартний",
            ComplexityLevel.TECHNICAL: "Технічний (для розробників)",
            ComplexityLevel.EXPERT: "Експертний (максимальна деталізація)",
        }
        return (
            f"Рівень складності: {descriptions[level]} ({level.value})\n"
            f"Доступні: {', '.join(self.available_levels())}\n"
            f"Змінити: /complexity <рівень>"
        )
