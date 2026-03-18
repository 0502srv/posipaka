"""Tool Output Compressor — стиснення великих tool outputs (секція 60.6)."""

from __future__ import annotations

import re


class ToolOutputCompressor:
    """
    Стискає великі tool outputs перед передачею до LLM.

    gmail_list → 50 листів → 10,000 tokens → стиснути до 500
    web_fetch → повна сторінка → 15,000 tokens → до 2,000
    """

    MAX_OUTPUT_TOKENS = 3000  # ~12,000 chars

    def compress(self, tool_name: str, output: str) -> str:
        """Автоматичний вибір компресора."""
        if len(output) < 1000:
            return output

        if "gmail" in tool_name or "email" in tool_name:
            return self.compress_email_output(output)
        if "calendar" in tool_name:
            return self.compress_calendar_output(output)
        if "web_fetch" in tool_name or "web_search" in tool_name:
            return self.compress_web_output(output)
        if "read_file" in tool_name:
            return self.compress_file_output(output)

        return self.generic_compress(output)

    def compress_email_output(self, output: str, max_emails: int = 10) -> str:
        """Зменшити деталі листів."""
        lines = output.strip().splitlines()
        result = []
        count = 0
        for line in lines:
            if count >= max_emails:
                result.append(f"... та ще {len(lines) - count} рядків")
                break
            result.append(line[:100])
            if line.startswith("📧") or line.startswith("•"):
                count += 1
        return "\n".join(result)

    def compress_calendar_output(self, output: str) -> str:
        """Стиснути події календаря."""
        lines = output.strip().splitlines()
        return "\n".join(line[:80] for line in lines[:20])

    def compress_web_output(self, output: str, max_chars: int = 3000) -> str:
        """Прибрати зайве з web content."""
        # Remove multiple blank lines
        text = re.sub(r"\n{3,}", "\n\n", output)
        # Remove very short lines (likely navigation)
        lines = [line for line in text.splitlines() if len(line.strip()) > 20]
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...[truncated]"
        return text

    def compress_file_output(
        self, output: str, max_lines: int = 50
    ) -> str:
        """Показати перші/останні рядки великого файлу."""
        lines = output.splitlines()
        if len(lines) <= max_lines:
            return output
        half = max_lines // 2
        return (
            "\n".join(lines[:half])
            + f"\n... [{len(lines) - max_lines} lines omitted] ...\n"
            + "\n".join(lines[-half:])
        )

    def generic_compress(self, output: str) -> str:
        """Загальне стиснення."""
        max_chars = self.MAX_OUTPUT_TOKENS * 4
        if len(output) <= max_chars:
            return output
        return output[:max_chars] + "\n...[truncated]"
