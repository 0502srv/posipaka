"""Prompt compression для зменшення токенів."""

from __future__ import annotations


class PromptCompressor:
    """Стиснення контексту для зменшення витрат на LLM.

    Стратегії:
    1. Видалення старих повідомлень за межами вікна
    2. Стиснення довгих tool outputs (>500 chars)
    3. Дедуплікація подібних повідомлень
    4. Видалення повторень system messages
    """

    DEFAULT_MAX_MESSAGES = 50
    TOOL_OUTPUT_MAX = 500
    TOOL_OUTPUT_HEAD = 200
    TOOL_OUTPUT_TAIL = 100

    def __init__(self, max_messages: int = DEFAULT_MAX_MESSAGES) -> None:
        self._max_messages = max_messages
        self._stats = {
            "messages_removed": 0,
            "tool_outputs_compressed": 0,
            "duplicates_removed": 0,
            "tokens_saved_estimate": 0,
        }

    def compress_context(
        self,
        messages: list[dict],
        max_messages: int | None = None,
    ) -> list[dict]:
        """Стиснути контекст розмови."""
        limit = max_messages or self._max_messages
        original_count = len(messages)

        # 1. Видалити старі повідомлення
        if len(messages) > limit:
            # Зберігаємо system + перші 2 + останні (limit - 2)
            system_msgs = [m for m in messages if m.get("role") == "system"]
            non_system = [m for m in messages if m.get("role") != "system"]
            keep_recent = limit - len(system_msgs)
            messages = system_msgs + non_system[-keep_recent:]
            self._stats["messages_removed"] += original_count - len(messages)

        # 2. Стиснути tool outputs
        messages = self._compress_tool_outputs(messages)

        # 3. Дедуплікація
        messages = self._deduplicate(messages)

        # 4. Видалити повторення system
        messages = self._deduplicate_system(messages)

        return messages

    def _compress_tool_outputs(self, messages: list[dict]) -> list[dict]:
        """Стиснути довгі tool outputs."""
        result = []
        for msg in messages:
            content = msg.get("content", "")
            if (
                msg.get("role") == "tool"
                and isinstance(content, str)
                and len(content) > self.TOOL_OUTPUT_MAX
            ):
                compressed = (
                    content[:self.TOOL_OUTPUT_HEAD]
                    + f"\n... [{len(content) - self.TOOL_OUTPUT_HEAD - self.TOOL_OUTPUT_TAIL} chars truncated] ...\n"
                    + content[-self.TOOL_OUTPUT_TAIL:]
                )
                self._stats["tool_outputs_compressed"] += 1
                self._stats["tokens_saved_estimate"] += (len(content) - len(compressed)) // 4
                result.append({**msg, "content": compressed})
            else:
                result.append(msg)
        return result

    def _deduplicate(self, messages: list[dict]) -> list[dict]:
        """Видалити послідовні дублікати."""
        if len(messages) < 2:
            return messages
        result = [messages[0]]
        for msg in messages[1:]:
            prev = result[-1]
            if (
                msg.get("role") == prev.get("role")
                and msg.get("content") == prev.get("content")
            ):
                self._stats["duplicates_removed"] += 1
                continue
            result.append(msg)
        return result

    def _deduplicate_system(self, messages: list[dict]) -> list[dict]:
        """Залишити тільки останній system message."""
        system_msgs = [m for m in messages if m.get("role") == "system"]
        if len(system_msgs) <= 1:
            return messages
        # Залишити тільки останній system
        last_system = system_msgs[-1]
        result = [m for m in messages if m.get("role") != "system"]
        result.insert(0, last_system)
        self._stats["duplicates_removed"] += len(system_msgs) - 1
        return result

    def get_compression_stats(self) -> dict:
        """Статистика стиснення."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        for key in self._stats:
            self._stats[key] = 0
