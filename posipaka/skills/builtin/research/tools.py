"""Research skill — глибоке дослідження з декількох джерел."""

from __future__ import annotations

from typing import Any


async def deep_research(topic: str, max_sources: int = 5) -> str:
    """Агрегує web_search + wiki_search для глибокого дослідження."""
    results = []

    # Web search
    try:
        from posipaka.integrations.browser.tools import web_search

        web_results = await web_search(topic, num_results=max_sources)
        results.append(f"## Веб-пошук\n{web_results}")
    except Exception as e:
        results.append(f"## Веб-пошук\nПомилка: {e}")

    # Wikipedia
    try:
        from posipaka.integrations.wikipedia.tools import wikipedia_summary

        wiki = await wikipedia_summary(topic)
        results.append(f"## Wikipedia\n{wiki}")
    except Exception as e:
        results.append(f"## Wikipedia\nПомилка: {e}")

    return f"# Дослідження: {topic}\n\n" + "\n\n".join(results)


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
