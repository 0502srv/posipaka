"""Text & Markdown formatting helpers."""

from __future__ import annotations

import html
import re


def truncate(text: str, max_length: int = 4096, suffix: str = "...") -> str:
    """Обрізати текст до max_length символів."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def markdown_to_telegram_html(text: str) -> str:
    """Convert standard Markdown (from LLM) to Telegram HTML.

    Telegram HTML supports: <b>, <i>, <code>, <pre>, <a>, <blockquote>.
    Does NOT support: headers, tables, horizontal rules.
    """
    # First, escape HTML special chars in the text
    # But preserve existing markdown formatting markers
    lines = text.split("\n")
    result_lines = []

    in_code_block = False
    code_block_lines: list[str] = []
    code_lang = ""

    for line in lines:
        # Code block toggle
        if line.strip().startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lang = line.strip().removeprefix("```").strip()
                code_block_lines = []
                continue
            else:
                in_code_block = False
                code_content = html.escape("\n".join(code_block_lines))
                if code_lang:
                    result_lines.append(
                        f'<pre><code class="language-{html.escape(code_lang)}">'
                        f"{code_content}</code></pre>"
                    )
                else:
                    result_lines.append(f"<pre>{code_content}</pre>")
                continue

        if in_code_block:
            code_block_lines.append(line)
            continue

        # Headers → bold
        header_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if header_match:
            header_text = html.escape(header_match.group(2))
            result_lines.append(f"\n<b>{header_text}</b>")
            continue

        # Horizontal rules → empty line
        if re.match(r"^---+$", line.strip()):
            result_lines.append("")
            continue

        # Blockquote
        if line.startswith("> "):
            quote_text = _convert_inline(line[2:])
            result_lines.append(f"<blockquote>{quote_text}</blockquote>")
            continue

        # Normal line — convert inline formatting
        result_lines.append(_convert_inline(line))

    # Handle unclosed code block
    if in_code_block and code_block_lines:
        code_content = html.escape("\n".join(code_block_lines))
        result_lines.append(f"<pre>{code_content}</pre>")

    text = "\n".join(result_lines)
    # Clean up excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _convert_inline(line: str) -> str:
    """Convert inline Markdown formatting to HTML."""
    # Escape HTML first, but track positions of markdown markers
    # Strategy: find and replace markdown patterns, escape the rest

    # Process inline code first (protect from other replacements)
    parts = re.split(r"(`[^`]+`)", line)
    result_parts = []
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            code_text = html.escape(part[1:-1])
            result_parts.append(f"<code>{code_text}</code>")
        else:
            converted = _convert_inline_text(part)
            result_parts.append(converted)
    return "".join(result_parts)


def _convert_inline_text(text: str) -> str:
    """Convert bold, italic, links in non-code text."""
    # Escape HTML special chars
    text = html.escape(text)

    # Links: [text](url) → <a href="url">text</a>
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )
    # Bold: **text** or __text__ → <b>text</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    # Italic: *text* or _text_ → <i>text</i> (but not inside words like file_name)
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", text)
    # Strikethrough: ~~text~~ → <s>text</s>
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    return text


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
