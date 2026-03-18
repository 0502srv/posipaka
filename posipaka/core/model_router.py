"""ModelRouter — вибирає модель залежно від складності запиту."""

from __future__ import annotations

import re

from loguru import logger


class ModelRouter:
    """
    Вибирає модель залежно від складності запиту.
    Haiku коштує в 20x менше ніж Opus.
    """

    SIMPLE_PATTERNS = [
        r"^(яка|яке|який|де|коли|хто|що таке)\s.{1,50}[?]?$",
        r"(переклади|translate)\s",
        r"(погода|weather|температура)",
        r"(котра година|яка дата|today|зараз)",
        r"^(привіт|hello|hi|hey)\s*[!.]?$",
    ]

    COMPLEX_PATTERNS = [
        r"(дослідж|research|проаналізуй|analyze)",
        r"(напиши звіт|write a report|розробни план)",
        r"(порівняй|compare|проти|versus)",
        r"(код|code|скрипт|script|програм)",
        r"(summary|підсумуй|коротко про)",
    ]

    def __init__(
        self,
        default_model: str = "mistral-large-latest",
        fast_model: str = "mistral-small-latest",
        complex_model: str = "mistral-large-latest",
    ) -> None:
        self.default_model = default_model
        self.fast_model = fast_model
        self.complex_model = complex_model

    def select(self, message: str, tools_count: int = 0) -> str:
        """Вибрати оптимальну модель для запиту."""
        msg_lower = message.lower().strip()

        # Якщо багато tools — потрібна розумніша модель
        if tools_count > 5:
            selected = self.default_model
            logger.debug(f"ModelRouter: {selected} (many tools: {tools_count})")
            return selected

        for pattern in self.COMPLEX_PATTERNS:
            if re.search(pattern, msg_lower):
                logger.debug(f"ModelRouter: {self.complex_model} (complex)")
                return self.complex_model

        for pattern in self.SIMPLE_PATTERNS:
            if re.search(pattern, msg_lower):
                logger.debug(f"ModelRouter: {self.fast_model} (simple)")
                return self.fast_model

        logger.debug(f"ModelRouter: {self.default_model} (default)")
        return self.default_model
