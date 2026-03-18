"""AgentOrchestrator — multi-agent orchestration."""

from __future__ import annotations

import asyncio

from loguru import logger

from posipaka.core.agents.base import AgentTask, BaseSpecializedAgent


class AgentOrchestrator:
    """Оркестратор спеціалізованих агентів."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseSpecializedAgent] = {}

    def register_agent(self, agent: BaseSpecializedAgent) -> None:
        self._agents[agent.name] = agent
        logger.debug(f"Registered agent: {agent.name}")

    def list_agents(self) -> list[dict]:
        return [
            {
                "name": a.name,
                "description": a.description,
                "capabilities": a.capabilities,
            }
            for a in self._agents.values()
        ]

    async def route(
        self, task_description: str, context: dict | None = None
    ) -> BaseSpecializedAgent | None:
        """Знайти найкращого агента для завдання."""
        best_agent = None
        best_score = 0.0

        for agent in self._agents.values():
            score = agent.can_handle(task_description)
            if score > best_score:
                best_score = score
                best_agent = agent

        if best_score >= 0.5:
            return best_agent
        return None

    async def execute(self, task_description: str, context: dict | None = None) -> str:
        """Виконати завдання через найкращого агента."""
        agent = await self.route(task_description, context)
        if not agent:
            return f"Немає підходящого агента для: {task_description}"

        task = AgentTask(description=task_description, context=context or {})
        logger.info(f"Routing to agent '{agent.name}': {task_description[:80]}")
        return await agent.execute(task)

    async def execute_parallel(self, tasks: list[dict]) -> list[str]:
        """Виконати декілька завдань паралельно."""

        async def _run(desc: str, ctx: dict) -> str:
            return await self.execute(desc, ctx)

        results = await asyncio.gather(
            *[_run(t["description"], t.get("context", {})) for t in tasks],
            return_exceptions=True,
        )
        return [str(r) for r in results]

    async def execute_sequential(self, tasks: list[dict]) -> list[str]:
        """Виконати завдання послідовно (результат попереднього → контекст наступного)."""
        results = []
        for t in tasks:
            ctx = t.get("context", {})
            if results:
                ctx["previous_result"] = results[-1]
            result = await self.execute(t["description"], ctx)
            results.append(result)
        return results
