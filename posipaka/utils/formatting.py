"""Text & Markdown formatting helpers."""

from __future__ import annotations


def truncate(text: str, max_length: int = 4096, suffix: str = "...") -> str:
    """Обрізати текст до max_length символів."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def split_message(text: str, max_length: int = 4096) -> list[str]:
    """Розбити довге повідомлення на частини."""
    if len(text) <= max_length:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
