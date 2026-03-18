"""Posipaka — News Integration (RSS/httpx)."""

from __future__ import annotations

from typing import Any

import httpx

from posipaka.security.injection import sanitize_external_content


async def get_news(topic: str, language: str = "uk", max_results: int = 5) -> str:
    """Отримати новини через Google News RSS."""
    try:
        from urllib.parse import quote_plus

        url = f"https://news.google.com/rss/search?q={quote_plus(topic)}&hl={language}"

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        # Parse RSS XML
        import xml.etree.ElementTree as ET

        root = ET.fromstring(resp.text)
        items = root.findall(".//item")[:max_results]

        if not items:
            return f"Новин не знайдено: {topic}"

        lines = [f"Новини: {topic}\n"]
        for item in items:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            lines.append(f"• {title}")
            if pub_date:
                lines.append(f"  {pub_date[:16]}")
            if link:
                lines.append(f"  {link}")
            lines.append("")

        return sanitize_external_content("\n".join(lines), source="google_news")
    except Exception as e:
        return f"Помилка новин: {e}"


async def get_top_headlines(country: str = "ua") -> str:
    """Топ заголовки."""
    return await get_news("*", language=country)


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="get_news",
            description="Search for recent news on a topic.",
            category="integration",
            handler=get_news,
            input_schema={
                "type": "object",
                "required": ["topic"],
                "properties": {
                    "topic": {"type": "string"},
                    "language": {"type": "string", "description": "Language (default: uk)"},
                    "max_results": {"type": "integer"},
                },
            },
            tags=["news"],
        )
    )

    registry.register(
        ToolDefinition(
            name="get_top_headlines",
            description="Get top news headlines.",
            category="integration",
            handler=get_top_headlines,
            input_schema={
                "type": "object",
                "properties": {
                    "country": {"type": "string", "description": "Country code (default: ua)"},
                },
            },
            tags=["news"],
        )
    )
