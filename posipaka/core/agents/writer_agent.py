"""Write texts, drafts, emails, documentation."""

from __future__ import annotations

from loguru import logger

from posipaka.core.agents.base import AgentTask, BaseSpecializedAgent


class WriterAgent(BaseSpecializedAgent):
    @property
    def name(self) -> str:
        return "writer"

    @property
    def description(self) -> str:
        return "Write texts, drafts, emails, documentation"

    @property
    def capabilities(self) -> list[str]:
        return [
            "write", "draft", "compose", "letter", "email", "blog",
            "article", "docs", "text", "напиши", "лист", "стаття",
            "документація", "текст", "чернетка",
        ]

    async def execute(self, task: AgentTask) -> str:
        try:
            context_info = "немає"
            if task.context:
                parts: list[str] = []
                if "code" in task.context:
                    parts.append(f"код: {task.context['code']}")
                if "data" in task.context:
                    parts.append(f"дані: {task.context['data']}")
                if parts:
                    context_info = "; ".join(parts)

            return (
                f"Завдання: {task.description}\n"
                f"Контекст: {context_info}\n\n"
                f"Підготовлено для обробки LLM."
            )

        except Exception as e:
            logger.error(f"WriterAgent error: {e}")
            return f"Помилка WriterAgent: {e}"
