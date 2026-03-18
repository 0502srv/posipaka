"""Graceful Degradation Matrix — поведінка при збоях компонентів."""

from __future__ import annotations

from enum import StrEnum


class ComponentStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class FailureMode(StrEnum):
    LLM_PRIMARY_DOWN = "llm_primary_down"
    LLM_ALL_DOWN = "llm_all_down"
    MEMORY_CHROMA_DOWN = "memory_chroma_down"
    MEMORY_SQLITE_DOWN = "memory_sqlite_down"
    INTERNET_DOWN = "internet_down"
    CHANNEL_DOWN = "channel_down"
    BUDGET_EXHAUSTED = "budget_exhausted"


DEGRADATION_MATRIX: dict[FailureMode, dict] = {
    FailureMode.LLM_PRIMARY_DOWN: {
        "strategy": "fallback_to_secondary",
        "user_message": "Основна AI-модель тимчасово недоступна. Переключаюсь на резервну.",
        "auto_recover": True,
        "recover_interval_sec": 60,
    },
    FailureMode.LLM_ALL_DOWN: {
        "strategy": "stop_processing",
        "user_message": "AI-модель тимчасово недоступна. Спробуйте через кілька хвилин.",
        "auto_recover": True,
        "recover_interval_sec": 30,
    },
    FailureMode.MEMORY_CHROMA_DOWN: {
        "strategy": "fallback_to_sqlite",
        "user_message": None,  # Silent fallback
        "auto_recover": True,
        "recover_interval_sec": 120,
    },
    FailureMode.MEMORY_SQLITE_DOWN: {
        "strategy": "ram_only",
        "user_message": "Пам'ять працює в обмеженому режимі. Дані можуть не зберегтись.",
        "auto_recover": True,
        "recover_interval_sec": 60,
    },
    FailureMode.INTERNET_DOWN: {
        "strategy": "offline_mode",
        "user_message": "Інтернет недоступний. Працюю в офлайн-режимі.",
        "auto_recover": True,
        "recover_interval_sec": 30,
    },
    FailureMode.CHANNEL_DOWN: {
        "strategy": "reconnect",
        "user_message": None,
        "auto_recover": True,
        "recover_interval_sec": 15,
    },
    FailureMode.BUDGET_EXHAUSTED: {
        "strategy": "stop_processing",
        "user_message": "Денний бюджет вичерпано. Спробуйте завтра або збільшіть ліміт.",
        "auto_recover": False,
    },
}


def get_degradation_response(failure: FailureMode) -> str | None:
    """Отримати повідомлення для користувача при збої."""
    entry = DEGRADATION_MATRIX.get(failure)
    if entry:
        return entry.get("user_message")
    return None
