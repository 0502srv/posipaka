"""Digest skill — щоденний дайджест з різних джерел."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from posipaka.security.injection import sanitize_external_content

_SOURCE_TIMEOUT = 5.0  # секунд на кожне джерело


async def _fetch_source(
    label: str, coro: Any,
) -> str:
    """Fetch одне джерело з таймаутом."""
    try:
        result = await asyncio.wait_for(coro, timeout=_SOURCE_TIMEOUT)
        return f"{label}:\n{result}"
    except TimeoutError:
        logger.debug(f"Digest: {label} timed out ({_SOURCE_TIMEOUT}s)")
        return f"{label}: таймаут"
    except Exception as e:
        logger.debug(f"Digest: {label} unavailable: {e}")
        return f"{label}: недоступно"


async def create_digest() -> str:
    """Створити дайджест: пошта, календар, погода, новини.

    Всі джерела завантажуються паралельно з таймаутом.
    Якщо джерело не відповідає — пропускається.
    """
    # Lazy imports — джерела можуть бути не встановлені
    sources: list[tuple[str, Any]] = []
    try:
        from posipaka.integrations.gmail.tools import gmail_list
        sources.append(("📬 Пошта", gmail_list(max_results=5)))
    except Exception:
        sources.append(("📬 Пошта", _noop("не налаштовано")))

    try:
        from posipaka.integrations.calendar.tools import calendar_list
        sources.append(("📅 Календар", calendar_list(days_ahead=2)))
    except Exception:
        sources.append(("📅 Календар", _noop("не налаштовано")))

    try:
        from posipaka.integrations.weather.tools import get_weather
        sources.append(("🌤 Погода", get_weather(city="Kyiv")))
    except Exception:
        sources.append(("🌤 Погода", _noop("не налаштовано")))

    try:
        from posipaka.integrations.news.tools import get_headlines
        sources.append(
            ("📰 Новини", get_headlines(country="ua", max_results=3))
        )
    except Exception:
        sources.append(("📰 Новини", _noop("не налаштовано")))

    # Паралельний fetch всіх джерел
    sections = await asyncio.gather(
        *[_fetch_source(label, coro) for label, coro in sources]
    )

    result = "=== Дайджест ===\n\n" + "\n\n".join(sections)
    return sanitize_external_content(result, source="digest")


async def _noop(msg: str) -> str:
    return msg


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="create_digest",
            description=(
                "Create daily digest with email, calendar, weather and news. "
                "Use when user asks for summary of the day or 'what's new'."
            ),
            category="productivity",
            handler=create_digest,
            input_schema={"type": "object", "properties": {}},
            tags=["digest", "aggregation"],
        )
    )
