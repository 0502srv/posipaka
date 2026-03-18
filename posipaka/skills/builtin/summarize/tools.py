"""Summarize skill — скорочення тексту та URL."""

from __future__ import annotations

from typing import Any


async def summarize_text(text: str, max_sentences: int = 5) -> str:
    """Скоротити текст (делегує до LLM через prompt)."""
    # Простий підхід: витягнути перші N речень
    import re

    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) <= max_sentences:
        return text
    return " ".join(sentences[:max_sentences]) + "..."


async def summarize_url(url: str, max_sentences: int = 5) -> str:
    """Скоротити вміст веб-сторінки."""
    from posipaka.integrations.browser.tools import web_fetch

    content = await web_fetch(url, extract_text=True)
    return await summarize_text(content, max_sentences)


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="summarize_text",
            description=(
                "Summarize a long text into key points. Use when user asks for TL;DR or summary."
            ),
            category="skill",
            handler=summarize_text,
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string", "description": "Text to summarize"},
                    "max_sentences": {
                        "type": "integer",
                        "description": "Max sentences (default 5)",
                    },
                },
            },
            tags=["text", "summarize"],
        )
    )

    registry.register(
        ToolDefinition(
            name="summarize_url",
            description="Fetch a URL and summarize its content.",
            category="skill",
            handler=summarize_url,
            input_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "description": "URL to summarize"},
                    "max_sentences": {"type": "integer"},
                },
            },
            tags=["text", "summarize", "web"],
        )
    )
