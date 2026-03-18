"""Тести для нових агентів: Security, Writer, Notification, Web."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from posipaka.core.agents.base import AgentTask


class TestSecurityAgent:
    @pytest.fixture
    def agent(self):
        from posipaka.core.agents.security_agent import SecurityAgent
        return SecurityAgent()

    def test_name(self, agent):
        assert agent.name == "security"

    def test_capabilities(self, agent):
        caps = agent.capabilities
        assert "security" in caps
        assert "безпека" in caps
        assert "scan" in caps

    def test_can_handle_security(self, agent):
        assert agent.can_handle("scan for secrets") >= 0.5
        assert agent.can_handle("перевір безпека") >= 0.5
        assert agent.can_handle("bake a cake") < 0.5

    @pytest.mark.asyncio
    async def test_audit_route(self, agent):
        with patch.object(agent, "_run_audit", new_callable=AsyncMock, return_value="OK"):
            task = AgentTask(description="run audit check")
            result = await agent.execute(task)
            assert "OK" in result

    @pytest.mark.asyncio
    async def test_scan_route(self, agent):
        with patch.object(
            agent, "_run_secret_scan",
            new_callable=AsyncMock,
            return_value="No secrets",
        ):
            task = AgentTask(description="scan for secrets")
            result = await agent.execute(task)
            assert "No secrets" in result

    @pytest.mark.asyncio
    async def test_default_runs_all(self, agent):
        with (
            patch.object(agent, "_run_audit", new_callable=AsyncMock, return_value="audit ok"),
            patch.object(agent, "_run_secret_scan", new_callable=AsyncMock, return_value="scan ok"),
            patch.object(agent, "_run_hygiene", new_callable=AsyncMock, return_value="hygiene ok"),
        ):
            task = AgentTask(description="check everything")
            result = await agent.execute(task)
            assert "audit ok" in result
            assert "scan ok" in result
            assert "hygiene ok" in result


class TestWriterAgent:
    @pytest.fixture
    def agent(self):
        from posipaka.core.agents.writer_agent import WriterAgent
        return WriterAgent()

    def test_name(self, agent):
        assert agent.name == "writer"

    def test_can_handle(self, agent):
        assert agent.can_handle("напиши лист") >= 0.5
        assert agent.can_handle("write a blog post") >= 0.5
        assert agent.can_handle("delete database") < 0.5

    @pytest.mark.asyncio
    async def test_execute(self, agent):
        task = AgentTask(description="write a blog post about Python")
        result = await agent.execute(task)
        assert "write a blog post" in result


class TestWebAgent:
    @pytest.fixture
    def agent(self):
        from posipaka.core.agents.web_agent import WebAgent
        return WebAgent()

    def test_name(self, agent):
        assert agent.name == "web"

    def test_can_handle(self, agent):
        assert agent.can_handle("search for Python tutorials") >= 0.5
        assert agent.can_handle("fetch https://example.com") >= 0.5

    @pytest.mark.asyncio
    async def test_search_route(self, agent):
        with patch(
            "posipaka.integrations.browser.tools.web_search",
            new_callable=AsyncMock,
            return_value="Results for Python",
        ):
            task = AgentTask(description="search for Python tutorials")
            result = await agent.execute(task)
            assert "Python" in result

    @pytest.mark.asyncio
    async def test_fetch_url(self, agent):
        with patch(
            "posipaka.integrations.browser.tools.web_fetch",
            new_callable=AsyncMock,
            return_value="Page content",
        ):
            task = AgentTask(description="fetch https://example.com/page")
            result = await agent.execute(task)
            assert "Page content" in result


class TestNotificationAgent:
    @pytest.fixture
    def agent(self):
        from posipaka.core.agents.notification_agent import NotificationAgent
        return NotificationAgent()

    def test_name(self, agent):
        assert agent.name == "notification"

    def test_can_handle(self, agent):
        assert agent.can_handle("send notification") >= 0.5
        assert agent.can_handle("дайджест") >= 0.5
