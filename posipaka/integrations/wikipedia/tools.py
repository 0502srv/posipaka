"""Posipaka — Wikipedia Integration."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from loguru import logger

from posipaka.security.injection import sanitize_external_content

WIKI_API = "https://{lang}.wikipedia.org/api/rest_v1"


async def wikipedia_search(query: str, lang: str = "uk") -> str:
    """Пошук у Wikipedia."""
    try:
        url = f"{WIKI_API.format(lang=lang)}/page/search/{quote(query)}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()

        data = response.json()
        pages = data.get("pages", [])
        if not pages:
            return f"Нічого не знайдено у Wikipedia ({lang}): {query}"

        lines = [f"Wikipedia ({lang}) — результати пошуку: '{query}'\n"]
        for p in pages[:5]:
            title = p.get("title", "")
            description = p.get("description", "")
            excerpt = p.get("excerpt", "")
            lines.append(f"• {title}")
            if description:
                lines.append(f"  {description}")
            if excerpt:
                # Remove HTML tags
                import re

                clean = re.sub(r"<[^>]+>", "", excerpt)[:200]
                lines.append(f"  {clean}")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Wikipedia search error: {e}")
        return f"Помилка пошуку Wikipedia: {e}"


async def wikipedia_summary(title: str, lang: str = "uk") -> str:
    """Отримати summary статті з Wikipedia."""
    try:
        url = f"{WIKI_API.format(lang=lang)}/page/summary/{quote(title)}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()

        data = response.json()
        page_title = data.get("title", title)
        extract = data.get("extract", "")
        page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")

        if not extract:
            return f"Стаття '{title}' не знайдена у Wikipedia ({lang})"

        result = f"# {page_title}\n\n{extract}"
        if page_url:
            result += f"\n\n🔗 {page_url}"

        return sanitize_external_content(result, source=f"wikipedia/{lang}")
    except Exception as e:
        logger.error(f"Wikipedia summary error: {e}")
        return f"Помилка Wikipedia: {e}"


def register(registry: Any) -> None:
    """Реєстрація Wikipedia tools."""
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="wikipedia_search",
            description="Search Wikipedia for articles on a topic.",
            category="integration",
            handler=wikipedia_search,
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "lang": {"type": "string", "description": "Language (default: uk)"},
                },
            },
            tags=["wikipedia", "knowledge"],
        )
    )

    registry.register(
        ToolDefinition(
            name="wikipedia_summary",
            description="Get a summary of a Wikipedia article by title.",
            category="integration",
            handler=wikipedia_summary,
            input_schema={
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {"type": "string", "description": "Article title"},
                    "lang": {"type": "string", "description": "Language (default: uk)"},
                },
            },
            tags=["wikipedia", "knowledge"],
        )
    )
