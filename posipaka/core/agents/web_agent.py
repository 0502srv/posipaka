"""Web search, page fetching, content extraction."""

from __future__ import annotations

import re

from loguru import logger

from posipaka.core.agents.base import AgentTask, BaseSpecializedAgent


class WebAgent(BaseSpecializedAgent):
    @property
    def name(self) -> str:
        return "web"

    @property
    def description(self) -> str:
        return "Web search, page fetching, content extraction"

    @property
    def capabilities(self) -> list[str]:
        return [
            "search", "fetch", "browse", "web", "url", "site",
            "page", "website", "пошук", "сайт", "сторінка",
        ]

    async def execute(self, task: AgentTask) -> str:
        try:
            desc = task.description.lower()

            if "search" in desc or "пошук" in desc or "знайди" in desc:
                from posipaka.integrations.browser.tools import web_search

                return await web_search(task.description)

            if "fetch" in desc or "url" in desc or "http" in desc:
                url_match = re.search(r"https?://\S+", task.description)
                if url_match:
                    from posipaka.integrations.browser.tools import web_fetch

                    return await web_fetch(url_match.group(0))

            # default: search
            from posipaka.integrations.browser.tools import web_search

            return await web_search(task.description)

        except Exception as e:
            logger.error(f"WebAgent error: {e}")
            return f"Помилка WebAgent: {e}"
