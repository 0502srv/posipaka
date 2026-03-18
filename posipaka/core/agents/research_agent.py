"""ResearchAgent — глибоке дослідження тем."""

from __future__ import annotations

from loguru import logger

from posipaka.core.agents.base import AgentTask, BaseSpecializedAgent


class ResearchAgent(BaseSpecializedAgent):
    """Агент для глибокого дослідження: web + wiki + аналіз."""

    @property
    def name(self) -> str:
        return "research"

    @property
    def description(self) -> str:
        return "Deep research using web search, Wikipedia, and source aggregation"

    @property
    def capabilities(self) -> list[str]:
        return ["research", "investigate", "дослідження", "що таке", "хто такий", "розкажи про"]

    async def execute(self, task: AgentTask) -> str:
        try:
            from posipaka.skills.builtin.research.tools import deep_research

            return await deep_research(task.description)
        except Exception as e:
            logger.error(f"ResearchAgent error: {e}")
            return f"Помилка дослідження: {e}"
