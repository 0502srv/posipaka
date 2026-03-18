"""Research skill — глибоке дослідження з декількох джерел."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger


async def _fetch_web(topic: str, max_sources: int) -> str:
    """Web search з graceful fallback."""
    try:
        from posipaka.integrations.browser.tools import web_search

        return f"## Веб-пошук\n{await web_search(topic, num_results=max_sources)}"
    except Exception as e:
        return f"## Веб-пошук\nПомилка: {e}"


async def _fetch_wiki(topic: str) -> str:
    """Wikipedia з graceful fallback."""
    try:
        from posipaka.integrations.wikipedia.tools import wikipedia_summary

        return f"## Wikipedia\n{await wikipedia_summary(topic)}"
    except Exception as e:
        return f"## Wikipedia\nПомилка: {e}"


async def deep_research(topic: str, max_sources: int = 5) -> str:
    """Паралельне дослідження: web_search + wikipedia одночасно."""
    web_result, wiki_result = await asyncio.gather(
        _fetch_web(topic, max_sources),
        _fetch_wiki(topic),
    )
    logger.debug(f"deep_research topic={topic!r} completed")
    return f"# Дослідження: {topic}\n\n{web_result}\n\n{wiki_result}"


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="deep_research",
            description=(
                "Conduct deep research on a topic using web search + Wikipedia."
                " Use for 'what is', 'who is', 'research' requests."
            ),
            category="skill",
            handler=deep_research,
            input_schema={
                "type": "object",
                "required": ["topic"],
                "properties": {
                    "topic": {"type": "string", "description": "Research topic"},
                    "max_sources": {"type": "integer", "description": "Max sources (default 5)"},
                },
            },
            tags=["research", "knowledge"],
        )
    )
