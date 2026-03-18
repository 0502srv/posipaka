"""Context Compaction — стиснення старих розмов через LLM summary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from posipaka.memory.backends.sqlite_backend import SQLiteBackend

COMPACTION_PROMPT = """\
Ти — система стиснення пам'яті AI-асистента.
Нижче надана розмова. Створи СТИСЛИЙ summary що зберігає:
1. Всі важливі факти (імена, дати, числа, рішення)
2. Контекст завдань що виконувались
3. Переваги та звички користувача що виявились
4. Незавершені задачі або домовленості

Формат: стислий текст до 300 слів. Тільки суть, без зайвого.

РОЗМОВА:
{conversation}

SUMMARY:
"""


class ContextCompactor:
    """
    Автоматичне стиснення старих повідомлень.

    Тригери:
        1. messages > COMPACTION_THRESHOLD (80)
        2. Щоночі о 03:00 (scheduled)
        3. Вручну: /compact
    """

    COMPACTION_THRESHOLD = 80
    KEEP_RECENT = 20

    def __init__(self, sqlite: SQLiteBackend) -> None:
        self._sqlite = sqlite

    async def should_compact(self, session_id: str) -> bool:
        stats = await self._sqlite.get_stats(session_id)
        return stats.get("count", 0) > self.COMPACTION_THRESHOLD

    async def compact(
        self, session_id: str, llm_complete_fn=None
    ) -> str:
        """
        Стиснути старі повідомлення.

        Args:
            session_id: ID сесії
            llm_complete_fn: async fn(system, messages) -> str
                             для генерації summary через LLM
        """
        messages = await self._sqlite.get_recent(
            session_id, limit=self.COMPACTION_THRESHOLD + 50
        )

        if len(messages) <= self.COMPACTION_THRESHOLD:
            return "Стиснення не потрібне."

        # Split: old messages to compact + recent to keep
        to_compact = messages[: -self.KEEP_RECENT]
        to_keep = messages[-self.KEEP_RECENT :]

        # Build conversation text
        conversation = "\n".join(
            f"[{m['role']}]: {m['content'][:200]}" for m in to_compact
        )

        # Generate summary
        if llm_complete_fn:
            try:
                prompt = COMPACTION_PROMPT.format(conversation=conversation)
                summary = await llm_complete_fn(
                    system="You are a memory compaction system.",
                    messages=[{"role": "user", "content": prompt}],
                )
            except Exception as e:
                logger.error(f"Compaction LLM error: {e}")
                # Fallback: simple truncation
                summary = self._simple_summary(to_compact)
        else:
            summary = self._simple_summary(to_compact)

        # Clear old messages and add summary
        await self._sqlite.clear_session(session_id)

        # Add summary as system message
        await self._sqlite.add_message(
            session_id,
            "system",
            f"[Стиснення пам'яті — {len(to_compact)} повідомлень]\n{summary}",
        )

        # Re-add recent messages
        for msg in to_keep:
            await self._sqlite.add_message(
                session_id, msg["role"], msg["content"]
            )

        compacted = len(to_compact)
        kept = len(to_keep)
        logger.info(
            f"Compacted session {session_id}: {compacted} → summary + {kept} recent"
        )
        return (
            f"Стиснуто {compacted} повідомлень у summary. "
            f"Збережено {kept} останніх."
        )

    @staticmethod
    def _simple_summary(messages: list[dict]) -> str:
        """Простий fallback summary без LLM."""
        facts = []
        for m in messages:
            content = m["content"][:100]
            if m["role"] == "user":
                facts.append(f"- Користувач: {content}")
            elif m["role"] == "assistant":
                facts.append(f"- Агент: {content}")

        if len(facts) > 20:
            facts = facts[:10] + ["..."] + facts[-10:]

        return "\n".join(facts)
