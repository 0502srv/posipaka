"""AnalysisAgent — аналіз даних, обчислення, візуалізація."""

from __future__ import annotations

from loguru import logger

from posipaka.core.agents.base import AgentTask, BaseSpecializedAgent


class AnalysisAgent(BaseSpecializedAgent):
    """Агент для аналізу даних та обчислень."""

    @property
    def name(self) -> str:
        return "analysis"

    @property
    def description(self) -> str:
        return "Data analysis, calculations, CSV processing, statistics"

    @property
    def capabilities(self) -> list[str]:
        return [
            "analyze",
            "calculate",
            "statistics",
            "csv",
            "data",
            "chart",
            "graph",
            "math",
            "аналіз",
            "обчисли",
            "порахуй",
            "статистика",
            "графік",
            "дані",
            "математика",
        ]

    async def execute(self, task: AgentTask) -> str:
        try:
            from posipaka.integrations.shell.tools import python_exec

            code = task.context.get("code")
            if code:
                return await python_exec(code)

            # Generate analysis code from description
            return (
                f"AnalysisAgent: Для аналізу даних, надайте:\n"
                f"1. Дані (файл або текст) в context\n"
                f"2. Або Python код для виконання в context['code']\n"
                f"\nЗавдання: {task.description}"
            )
        except Exception as e:
            logger.error(f"AnalysisAgent error: {e}")
            return f"Помилка AnalysisAgent: {e}"
