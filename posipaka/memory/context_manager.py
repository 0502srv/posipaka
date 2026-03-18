"""Context Manager — розумне управління контекстним вікном."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posipaka.memory.manager import MemoryManager


class ContextManager:
    """
    Розумне управління контекстом замість "передати все".

    Проблема: кожен turn дорожчий — весь контекст передається знову.
    Turn 1: 500 tokens → Turn 50: 25,000 tokens (50x дорожче!)
    """

    KEEP_RECENT_MESSAGES = 10
    SUMMARIZE_THRESHOLD = 20
    MAX_CONTEXT_TOKENS = 15_000

    def __init__(self, memory: MemoryManager) -> None:
        self._memory = memory

    async def build_optimal_context(
        self,
        session_id: str,
        current_message: str,
    ) -> list[dict]:
        """
        Будує оптимальний контекст:
        1. Останні KEEP_RECENT_MESSAGES
        2. Summary старих повідомлень (якщо є)
        3. Semantic search по поточному запиту
        4. Trim до MAX_CONTEXT_TOKENS
        """
        context: list[dict] = []

        # Recent messages
        recent = await self._memory.get_recent(session_id, limit=self.KEEP_RECENT_MESSAGES)

        # Semantic search для релевантних старих повідомлень
        relevant = await self._memory.search_relevant(session_id, current_message, limit=3)
        if relevant:
            combined = "\n".join(relevant)
            context.append(
                {
                    "role": "user",
                    "content": f"[Relevant past context]\n{combined}",
                }
            )

        # Add recent messages
        for msg in recent:
            context.append({"role": msg["role"], "content": msg["content"]})

        # Trim
        return self._trim_to_token_limit(context, self.MAX_CONTEXT_TOKENS)

    async def should_compact(self, session_id: str) -> bool:
        """Чи потрібно стиснути контекст."""
        stats = await self._memory.get_stats(session_id)
        return stats.get("db_messages", 0) > self.SUMMARIZE_THRESHOLD

    @staticmethod
    def _trim_to_token_limit(messages: list[dict], max_tokens: int) -> list[dict]:
        """Обрізати повідомлення до ліміту токенів (приблизно)."""
        from posipaka.core.cost_guard import CostGuard

        total = 0
        result = []
        for msg in reversed(messages):
            tokens = CostGuard.estimate_tokens(msg.get("content", ""))
            if total + tokens > max_tokens:
                break
            result.insert(0, msg)
            total += tokens
        return result

    @staticmethod
    def estimate_tokens(messages: list[dict]) -> int:
        """Оцінка токенів через CostGuard."""
        from posipaka.core.cost_guard import CostGuard

        return sum(
            CostGuard.estimate_tokens(m.get("content", ""))
            for m in messages
        )
