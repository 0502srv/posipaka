"""CostGuard — контроль витрат на LLM запити."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC

from loguru import logger


@dataclass
class CostRecord:
    timestamp: float
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    session_id: str


class CostLimitExceededError(Exception):
    def __init__(self, reason: str, spent: float, limit: float) -> None:
        self.reason = reason
        self.spent = spent
        self.limit = limit
        super().__init__(reason)


class CostGuard:
    """Перевіряє бюджет ПЕРЕД кожним LLM call."""

    PRICING: dict[str, dict[str, float]] = {
        "claude-sonnet-4-20250514": {"input": 3.0e-6, "output": 15.0e-6},
        "claude-haiku-4-5-20251001": {"input": 0.8e-6, "output": 4.0e-6},
        "claude-opus-4-20250514": {"input": 15.0e-6, "output": 75.0e-6},
        "gpt-4o": {"input": 2.5e-6, "output": 10.0e-6},
        "gpt-4o-mini": {"input": 0.15e-6, "output": 0.60e-6},
        # Mistral
        "mistral-large-latest": {"input": 2.0e-6, "output": 6.0e-6},
        "mistral-small-latest": {"input": 0.1e-6, "output": 0.3e-6},
        # Gemini
        "gemini-2.0-flash": {"input": 0.1e-6, "output": 0.4e-6},
        "gemini-2.5-pro-preview-06-05": {"input": 1.25e-6, "output": 10.0e-6},
        # Groq
        "llama-3.3-70b-versatile": {"input": 0.59e-6, "output": 0.79e-6},
        "llama-3.1-8b-instant": {"input": 0.05e-6, "output": 0.08e-6},
        # DeepSeek
        "deepseek-chat": {"input": 0.14e-6, "output": 0.28e-6},
        "deepseek-reasoner": {"input": 0.55e-6, "output": 2.19e-6},
        # xAI
        "grok-3": {"input": 3.0e-6, "output": 15.0e-6},
        "grok-3-mini": {"input": 0.3e-6, "output": 0.5e-6},
        "_default": {"input": 5.0e-6, "output": 25.0e-6},
    }

    def __init__(
        self,
        daily_budget_usd: float = 5.0,
        per_request_max_usd: float = 0.50,
        per_session_max_usd: float = 2.0,
        warning_threshold: float = 0.8,
        timezone: str = "UTC",
    ) -> None:
        self.daily_budget = daily_budget_usd
        self.per_request_max = per_request_max_usd
        self.per_session_max = per_session_max_usd
        self.warning_threshold = warning_threshold
        self._timezone = timezone
        self._records: list[CostRecord] = []
        self._warning_sent_today = False

    # Коефіцієнти токенізації по провайдерах/моделях.
    # char_per_token: скільки символів у середньому на 1 токен.
    # Менше значення = більше токенів на той самий текст.
    _TOKENIZER_PROFILES: dict[str, dict[str, float]] = {
        # Anthropic: ~3.5 chars/token EN, ~1.8 UA
        "claude": {"en": 3.5, "ua": 1.8},
        # OpenAI (tiktoken): ~4.0 EN, ~1.5 UA
        "gpt": {"en": 4.0, "ua": 1.5},
        # Mistral (SentencePiece): ~3.8 EN, ~1.6 UA
        "mistral": {"en": 3.8, "ua": 1.6},
        # Gemini (SentencePiece): ~4.0 EN, ~1.7 UA
        "gemini": {"en": 4.0, "ua": 1.7},
        # Llama/Groq (SentencePiece): ~3.5 EN, ~1.5 UA
        "llama": {"en": 3.5, "ua": 1.5},
        # DeepSeek (BPE): ~3.8 EN, ~1.4 UA
        "deepseek": {"en": 3.8, "ua": 1.4},
        # Grok/xAI: ~3.8 EN, ~1.6 UA
        "grok": {"en": 3.8, "ua": 1.6},
        # Fallback
        "_default": {"en": 3.7, "ua": 1.6},
    }

    @classmethod
    def _get_tokenizer_profile(
        cls, model: str,
    ) -> dict[str, float]:
        """Знайти профіль tokenizer'а за назвою моделі."""
        model_lower = model.lower()
        for prefix, profile in cls._TOKENIZER_PROFILES.items():
            if prefix in model_lower:
                return profile
        return cls._TOKENIZER_PROFILES["_default"]

    @classmethod
    def estimate_tokens(cls, text: str, model: str = "") -> int:
        """Оцінка токенів, адаптована під конкретну модель.

        Різні tokenizer'и (BPE, SentencePiece) по-різному
        обробляють кирилицю та латиницю.
        """
        if not text:
            return 0
        profile = cls._get_tokenizer_profile(model)
        # Визначаємо частку non-ASCII (кирилиця)
        non_ascii = sum(1 for c in text if ord(c) > 127)
        total = max(len(text), 1)
        ascii_ratio = 1.0 - (non_ascii / total)
        # Зважений chars_per_token
        cpt = profile["en"] * ascii_ratio + profile["ua"] * (
            1 - ascii_ratio
        )
        return max(1, int(total / cpt))

    def check_before_call(
        self,
        model: str,
        estimated_input_tokens: int,
        session_id: str,
        max_output_tokens: int = 4096,
    ) -> tuple[bool, str]:
        """Перевірити бюджет перед LLM call. Returns (allowed, reason)."""
        pricing = self.PRICING.get(model, self.PRICING["_default"])
        estimated_cost = (
            estimated_input_tokens * pricing["input"]
            + max_output_tokens * pricing["output"]
        )

        if estimated_cost > self.per_request_max:
            return False, (
                f"Оціночна вартість ${estimated_cost:.3f} "
                f"перевищує ліміт запиту ${self.per_request_max:.2f}."
            )

        daily_spent = self._get_daily_total()
        if daily_spent + estimated_cost > self.daily_budget:
            return False, (
                f"Денний бюджет вичерпано: витрачено ${daily_spent:.2f} з ${self.daily_budget:.2f}."
            )

        session_spent = self._get_session_total(session_id)
        if session_spent + estimated_cost > self.per_session_max:
            return False, (f"Ліміт сесії: ${session_spent:.2f} з ${self.per_session_max:.2f}.")

        if (
            daily_spent + estimated_cost
        ) / self.daily_budget >= self.warning_threshold and not self._warning_sent_today:
            self._warning_sent_today = True
            logger.warning(f"Budget warning: ${daily_spent:.2f} / ${self.daily_budget:.2f}")

        return True, "ok"

    def record(
        self, model: str, input_tokens: int, output_tokens: int, session_id: str
    ) -> CostRecord:
        """Записати фактичне використання після LLM call."""
        pricing = self.PRICING.get(model, self.PRICING["_default"])
        cost = input_tokens * pricing["input"] + output_tokens * pricing["output"]
        rec = CostRecord(time.time(), model, input_tokens, output_tokens, cost, session_id)
        self._records.append(rec)
        return rec

    def get_daily_report(self) -> str:
        total = self._get_daily_total()
        remaining = max(0, self.daily_budget - total)
        count = sum(1 for r in self._records if r.timestamp >= self._today_start())
        return (
            f"Витрачено сьогодні: ${total:.2f} / ${self.daily_budget:.2f}\n"
            f"Залишок: ${remaining:.2f}\n"
            f"Запитів: {count}"
        )

    def _today_start(self) -> float:
        """Початок поточного дня (timezone-aware)."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        try:
            tz = ZoneInfo(self._timezone)
        except (KeyError, ImportError):
            tz = UTC
        now = datetime.now(tz)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight.timestamp()

    def _get_daily_total(self) -> float:
        start = self._today_start()
        return sum(r.cost_usd for r in self._records if r.timestamp >= start)

    def _get_session_total(self, session_id: str) -> float:
        return sum(r.cost_usd for r in self._records if r.session_id == session_id)
