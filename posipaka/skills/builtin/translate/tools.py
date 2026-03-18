"""Translate skill — переклад через LLM."""

from __future__ import annotations

from typing import Any


async def translate_text(
    text: str, target_language: str = "en", source_language: str = "auto"
) -> str:
    """Перекласти текст (результат повертається як підказка для LLM)."""
    return (
        f"[Translation request]\n"
        f"Source language: {source_language}\n"
        f"Target language: {target_language}\n"
        f"Text: {text}\n\n"
        f"Please provide the translation."
    )


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="translate_text",
            description="Translate text between languages. LLM handles the actual translation.",
            category="skill",
            handler=translate_text,
            input_schema={
                "type": "object",
                "required": ["text", "target_language"],
                "properties": {
                    "text": {"type": "string", "description": "Text to translate"},
                    "target_language": {
                        "type": "string",
                        "description": "Target language (e.g. 'en', 'uk', 'de')",
                    },
                    "source_language": {
                        "type": "string",
                        "description": "Source language (default: auto-detect)",
                    },
                },
            },
            tags=["text", "translate"],
        )
    )
