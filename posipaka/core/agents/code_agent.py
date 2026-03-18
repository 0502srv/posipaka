"""CodeAgent — виконання коду, GitHub операції, аналіз коду."""

from __future__ import annotations

from loguru import logger

from posipaka.core.agents.base import AgentTask, BaseSpecializedAgent


class CodeAgent(BaseSpecializedAgent):
    """Агент для роботи з кодом: виконання Python, аналіз, GitHub."""

    @property
    def name(self) -> str:
        return "code"

    @property
    def description(self) -> str:
        return "Execute Python code, analyze code, interact with GitHub"

    @property
    def capabilities(self) -> list[str]:
        return [
            "python",
            "code",
            "script",
            "execute",
            "run",
            "github",
            "git",
            "repo",
            "commit",
            "код",
            "скрипт",
            "виконай",
            "запусти",
            "debug",
            "analyze",
            "refactor",
        ]

    async def execute(self, task: AgentTask) -> str:
        try:
            from posipaka.integrations.shell.tools import python_exec

            # If task contains code to execute
            code = task.context.get("code", "")
            if code:
                return await python_exec(code)

            # If task is a description, generate simple analysis
            return (
                f"CodeAgent: Для виконання коду, надайте код у context['code'].\n"
                f"Завдання: {task.description}"
            )
        except Exception as e:
            logger.error(f"CodeAgent error: {e}")
            return f"Помилка CodeAgent: {e}"
