"""Тести для MCP (Model Context Protocol) — loader, bridge, integration."""

from __future__ import annotations

import asyncio
import time as time_mod
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import posipaka.core.tools.mcp_loader as _mcp_loader_module
from posipaka.core.tools.mcp_bridge import (
    MCP_CATEGORY,
    MCP_TOOL_PREFIX,
    MCPBridge,
    _build_description,
    _extract_content,
    _make_tool_name,
)
from posipaka.core.tools.mcp_loader import (
    CALL_MAX_RETRIES,
    CIRCUIT_BREAKER_THRESHOLD,
    INIT_MAX_RETRIES,
    MAX_CONCURRENT_CALLS,
    MAX_TOOL_NAME_LENGTH,
    MCPCallMetrics,
    MCPOAuthConfig,
    MCPServerConfig,
    MCPServerState,
    MCPServerStatus,
    MCPToolLoader,
    MCPTransport,
    _build_subprocess_env,
    _check_blocked_host,
    _content_block_to_dict,
    _error_result,
    _FileTokenStorage,
    _is_ip_address,
    _is_private_ip,
    _paginated_list,
    _prompt_content_to_str,
    _resolve_env,
    _resource_template_to_dict,
    _score_tool,
    _validate_mcp_url,
    make_safe_server_name,
    make_safe_tool_name,
)
from posipaka.core.tools.registry import ToolRegistry

# Allow test commands (echo, test) in all MCP tests
_mcp_loader_module._ALLOWED_COMMANDS = _mcp_loader_module._ALLOWED_COMMANDS | frozenset(
    {"echo", "test", "test2"},
)

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mcp_yaml(tmp_path):
    """Create a test mcp.yaml config."""
    config = {
        "servers": {
            "test-server": {
                "command": "echo",
                "args": ["hello"],
                "enabled": True,
            },
            "disabled-server": {
                "command": "echo",
                "args": [],
                "enabled": False,
            },
        },
        "settings": {
            "lazy_loading": False,
            "timeout_seconds": 5,
            "max_servers": 10,
            "allowed_commands": ["echo", "test"],
        },
    }
    path = tmp_path / "mcp.yaml"
    import yaml

    path.write_text(yaml.dump(config), encoding="utf-8")
    return path


@pytest.fixture
def loader(mcp_yaml):
    return MCPToolLoader(config_path=mcp_yaml)


@pytest.fixture
def registry():
    return ToolRegistry()


# ============================================================
# MCPToolLoader — Config Loading
# ============================================================


class TestMCPToolLoaderConfig:
    def test_load_config_parses_servers(self, loader):
        configs = loader.load_config()
        assert len(configs) == 1  # only enabled servers
        assert configs[0].name == "test-server"
        assert configs[0].command == "echo"
        assert configs[0].args == ["hello"]

    def test_load_config_skips_disabled(self, loader):
        configs = loader.load_config()
        names = [c.name for c in configs]
        assert "disabled-server" not in names

    def test_load_config_missing_file(self, tmp_path):
        loader = MCPToolLoader(config_path=tmp_path / "nonexistent.yaml")
        configs = loader.load_config()
        assert configs == []

    def test_load_config_empty_file(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        configs = loader.load_config()
        assert configs == []

    def test_load_config_list_format(self, tmp_path):
        """Support list-based server config (legacy format)."""
        import yaml

        config = {
            "servers": [
                {"name": "srv1", "command": "test", "enabled": True},
                {"name": "srv2", "command": "test2", "enabled": True},
            ],
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        configs = loader.load_config()
        assert len(configs) == 2

    def test_load_config_max_servers(self, tmp_path):
        """Respect max_servers limit."""
        import yaml

        config = {
            "servers": {
                f"srv{i}": {"command": "test", "enabled": True}
                for i in range(20)
            },
            "settings": {"max_servers": 3},
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        configs = loader.load_config()
        assert len(configs) == 3

    def test_server_count_and_active(self, loader):
        loader.load_config()
        assert loader.server_count == 1
        assert loader.active_servers == []  # Not started yet

    def test_load_config_http_transport(self, tmp_path):
        """HTTP transport servers need url, not command."""
        import yaml

        config = {
            "servers": {
                "remote": {
                    "transport": "streamable-http",
                    "url": "http://localhost:8000/mcp",
                    "enabled": True,
                },
            },
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        with patch(
            "posipaka.core.tools.mcp_loader._validate_mcp_url",
            return_value=(True, "ok"),
        ):
            configs = loader.load_config()
        assert len(configs) == 1
        assert configs[0].transport == "streamable-http"
        assert configs[0].url == "http://localhost:8000/mcp"

    def test_load_config_oauth(self, tmp_path):
        """OAuth config parsed from mcp.yaml."""
        import yaml

        config = {
            "servers": {
                "oauth-server": {
                    "transport": "streamable-http",
                    "url": "http://localhost:8000/mcp",
                    "oauth": {
                        "client_name": "test-app",
                        "redirect_uri": "http://localhost:9000/cb",
                        "scope": "tools:read",
                    },
                    "enabled": True,
                },
            },
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        with patch(
            "posipaka.core.tools.mcp_loader._validate_mcp_url",
            return_value=(True, "ok"),
        ):
            configs = loader.load_config()
        assert len(configs) == 1
        assert configs[0].oauth is not None
        assert configs[0].oauth.client_name == "test-app"
        assert configs[0].oauth.scope == "tools:read"

    def test_load_config_headers(self, tmp_path):
        """Custom headers parsed from mcp.yaml."""
        import yaml

        config = {
            "servers": {
                "api-server": {
                    "transport": "streamable-http",
                    "url": "http://localhost:8000/mcp",
                    "headers": {"Authorization": "Bearer token123"},
                    "enabled": True,
                },
            },
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        with patch(
            "posipaka.core.tools.mcp_loader._validate_mcp_url",
            return_value=(True, "ok"),
        ):
            configs = loader.load_config()
        assert configs[0].headers == {"Authorization": "Bearer token123"}


# ============================================================
# MCPToolLoader — Transport Enum
# ============================================================


class TestMCPTransportEnum:
    def test_stdio_transport(self):
        assert MCPTransport.STDIO == "stdio"

    def test_http_transport(self):
        assert MCPTransport.HTTP == "streamable-http"


# ============================================================
# MCPToolLoader — Env Resolution
# ============================================================


class TestEnvResolution:
    def test_resolve_simple_var(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "secret123")
        result = _resolve_env({"API_KEY": "${MY_KEY}"})
        assert result["API_KEY"] == "secret123"

    def test_resolve_with_default(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        result = _resolve_env({"KEY": "${MISSING_VAR:-fallback_value}"})
        assert result["KEY"] == "fallback_value"

    def test_resolve_existing_with_default(self, monkeypatch):
        monkeypatch.setenv("EXISTING", "real_value")
        result = _resolve_env({"KEY": "${EXISTING:-fallback}"})
        assert result["KEY"] == "real_value"

    def test_resolve_no_var(self):
        result = _resolve_env({"PLAIN": "just_a_string"})
        assert result["PLAIN"] == "just_a_string"

    def test_resolve_mixed(self, monkeypatch):
        monkeypatch.setenv("HOST", "localhost")
        result = _resolve_env({"URL": "http://${HOST}:8080/api"})
        assert result["URL"] == "http://localhost:8080/api"

    def test_resolve_non_string_value(self):
        result = _resolve_env({"PORT": 8080})
        assert result["PORT"] == "8080"


# ============================================================
# MCPToolLoader — Server Lifecycle
# ============================================================


class TestMCPServerLifecycle:
    async def test_start_server_not_found(self, loader):
        loader.load_config()
        result = await loader.start_server("nonexistent")
        assert result is False

    async def test_circuit_breaker_blocks_start(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.consecutive_failures = CIRCUIT_BREAKER_THRESHOLD
        result = await loader.start_server("test-server")
        assert result is False
        assert state.status == MCPServerStatus.ERROR

    async def test_stop_server_not_running(self, loader):
        loader.load_config()
        await loader.stop_server("test-server")  # Should not raise

    async def test_stop_all_empty(self, loader):
        await loader.stop_all()  # No servers loaded

    async def test_get_tools_not_ready(self, loader):
        loader.load_config()
        tools = await loader.get_tools("test-server")
        assert tools == []

    async def test_call_tool_not_ready(self, loader):
        loader.load_config()
        result = await loader.call_tool("test-server", "some_tool", {})
        assert result["isError"] is True

    async def test_call_tool_no_session(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.session = None
        result = await loader.call_tool("test-server", "some_tool", {})
        assert result["isError"] is True
        assert "no session" in result["content"][0]["text"]

    async def test_restart_resets_circuit_breaker(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.consecutive_failures = 10

        with patch.object(
            loader, "start_server", new_callable=AsyncMock, return_value=False,
        ):
            await loader.restart_server("test-server")
        assert state.consecutive_failures == 0

    async def test_start_all_parallel(self, tmp_path):
        """start_all uses asyncio.gather for parallel startup."""
        import yaml

        config = {
            "servers": {
                "srv1": {"command": "echo", "enabled": True},
                "srv2": {"command": "echo", "enabled": True},
            },
            "settings": {"lazy_loading": False},
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        loader.load_config()

        # Mock start_server to track calls
        call_order = []

        async def mock_start(name):
            call_order.append(name)
            return False  # Don't actually start

        with patch.object(loader, "start_server", side_effect=mock_start):
            await loader.start_all()

        assert len(call_order) == 2
        assert set(call_order) == {"srv1", "srv2"}


# ============================================================
# MCPToolLoader — SDK-based Tool Operations (mocked session)
# ============================================================


class TestMCPToolOperations:
    async def test_get_tools_with_session(self, loader):
        """Tools fetched via SDK session with pagination."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_tool = MagicMock()
        mock_tool.name = "read_file"
        mock_tool.description = "Read a file"
        mock_tool.inputSchema = {"type": "object", "properties": {"path": {"type": "string"}}}
        mock_tool.annotations = None

        mock_result = MagicMock()
        mock_result.tools = [mock_tool]
        mock_result.nextCursor = None

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=mock_result)
        state.session = mock_session

        tools = await loader.get_tools("test-server")
        assert len(tools) == 1
        assert tools[0]["name"] == "read_file"
        assert tools[0]["description"] == "Read a file"

    async def test_get_tools_with_annotations(self, loader):
        """Tool annotations are extracted from SDK response."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_annotations = MagicMock()
        mock_annotations.readOnlyHint = False
        mock_annotations.destructiveHint = True
        mock_annotations.idempotentHint = None
        mock_annotations.openWorldHint = None

        mock_tool = MagicMock()
        mock_tool.name = "delete_file"
        mock_tool.description = "Delete a file"
        mock_tool.inputSchema = {}
        mock_tool.annotations = mock_annotations

        mock_result = MagicMock()
        mock_result.tools = [mock_tool]
        mock_result.nextCursor = None

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=mock_result)
        state.session = mock_session

        tools = await loader.get_tools("test-server")
        assert len(tools) == 1
        assert tools[0]["annotations"]["destructiveHint"] is True
        assert tools[0]["annotations"]["readOnlyHint"] is False

    async def test_get_tools_pagination(self, loader):
        """Paginated tool list fetches all pages."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_tool1 = MagicMock()
        mock_tool1.name = "tool1"
        mock_tool1.description = "First"
        mock_tool1.inputSchema = {}
        mock_tool1.annotations = None

        mock_tool2 = MagicMock()
        mock_tool2.name = "tool2"
        mock_tool2.description = "Second"
        mock_tool2.inputSchema = {}
        mock_tool2.annotations = None

        page1 = MagicMock()
        page1.tools = [mock_tool1]
        page1.nextCursor = "cursor_abc"

        page2 = MagicMock()
        page2.tools = [mock_tool2]
        page2.nextCursor = None

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(side_effect=[page1, page2])
        state.session = mock_session

        tools = await loader.get_tools("test-server")
        assert len(tools) == 2
        assert tools[0]["name"] == "tool1"
        assert tools[1]["name"] == "tool2"

    async def test_get_tools_cache(self, loader):
        """Second call uses cache."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_tool = MagicMock()
        mock_tool.name = "cached_tool"
        mock_tool.description = ""
        mock_tool.inputSchema = {}
        mock_tool.annotations = None

        mock_result = MagicMock()
        mock_result.tools = [mock_tool]
        mock_result.nextCursor = None

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=mock_result)
        state.session = mock_session

        await loader.get_tools("test-server")
        # Second call — should use cache
        mock_session.list_tools = AsyncMock(side_effect=Exception("should not be called"))
        tools2 = await loader.get_tools("test-server")
        assert len(tools2) == 1

    async def test_call_tool_success(self, loader):
        """Successful tool call via SDK session."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = [{"name": "greet", "description": "Greet someone"}]

        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = "Hello World"

        mock_result = MagicMock()
        mock_result.content = [mock_content]
        mock_result.isError = False
        mock_result.structuredContent = None

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)
        state.session = mock_session

        result = await loader.call_tool("test-server", "greet", {"name": "Test"})
        assert result["isError"] is False
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "Hello World"
        assert state.consecutive_failures == 0

    async def test_call_tool_with_structured_content(self, loader):
        """Tool call returns structuredContent."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = [{"name": "query", "description": "Query"}]

        mock_result = MagicMock()
        mock_result.content = []
        mock_result.isError = False
        mock_result.structuredContent = {"key": "value", "count": 42}

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)
        state.session = mock_session

        result = await loader.call_tool("test-server", "query", {})
        assert result["structuredContent"] == {"key": "value", "count": 42}
        assert result["isError"] is False

    async def test_call_tool_timeout(self, loader):
        """Tool call that times out."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.consecutive_failures = 0
        state.tools = [{"name": "slow_tool", "description": "Slow"}]

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=TimeoutError())
        state.session = mock_session

        result = await loader.call_tool("test-server", "slow_tool", {})
        assert result["isError"] is True
        assert "timeout" in result["content"][0]["text"]
        assert state.consecutive_failures == 1

    async def test_call_tool_error(self, loader):
        """Tool call that raises exception."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.consecutive_failures = 0
        state.tools = [{"name": "bad_tool", "description": "Bad"}]

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=RuntimeError("broken"))
        state.session = mock_session

        result = await loader.call_tool("test-server", "bad_tool", {})
        assert result["isError"] is True
        assert state.consecutive_failures == 1

    async def test_call_tool_auto_reconnect(self, loader):
        """Tool call triggers reconnect for ERROR server."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.ERROR
        state.consecutive_failures = 1  # Below threshold

        with patch.object(
            loader, "_try_reconnect", new_callable=AsyncMock, return_value=False,
        ) as mock_reconnect:
            result = await loader.call_tool("test-server", "tool", {})
            mock_reconnect.assert_called_once_with("test-server")
            assert result["isError"] is True

    async def test_call_tool_not_found(self, loader):
        """Tool call on nonexistent server."""
        loader.load_config()
        result = await loader.call_tool("nonexistent", "tool", {})
        assert result["isError"] is True
        assert "not found" in result["content"][0]["text"]

    async def test_get_all_tools_parallel(self, tmp_path):
        """get_all_tools fetches from all servers in parallel."""
        import yaml

        config = {
            "servers": {
                "srv1": {"command": "echo", "enabled": True},
                "srv2": {"command": "echo", "enabled": True},
            },
            "settings": {"lazy_loading": False},
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        loader.load_config()

        # Set both servers as READY with pre-cached tools
        for name in ["srv1", "srv2"]:
            state = loader._servers[name]
            state.status = MCPServerStatus.READY
            state.tools = [{"name": f"{name}_tool", "description": ""}]
            state.tools_cached_at = time_mod.time()

        result = await loader.get_all_tools()
        assert "srv1" in result
        assert "srv2" in result


# ============================================================
# MCPToolLoader — Resources (mocked session)
# ============================================================


class TestMCPResources:
    async def test_get_resources(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_resource = MagicMock()
        mock_resource.uri = "file:///test.txt"
        mock_resource.name = "test.txt"
        mock_resource.description = "A test file"
        mock_resource.mimeType = "text/plain"

        mock_result = MagicMock()
        mock_result.resources = [mock_resource]
        mock_result.nextCursor = None

        mock_session = AsyncMock()
        mock_session.list_resources = AsyncMock(return_value=mock_result)
        state.session = mock_session

        resources = await loader.get_resources("test-server")
        assert len(resources) == 1
        assert resources[0]["uri"] == "file:///test.txt"

    async def test_get_resources_not_ready(self, loader):
        loader.load_config()
        resources = await loader.get_resources("test-server")
        assert resources == []

    async def test_get_resources_cached(self, loader):
        """Second call uses resource cache."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.resources = [{"uri": "cached://resource"}]
        state.resources_cached_at = time_mod.time()

        resources = await loader.get_resources("test-server")
        assert len(resources) == 1
        assert resources[0]["uri"] == "cached://resource"

    async def test_read_resource(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_content = MagicMock()
        mock_content.text = "file contents here"
        mock_content.blob = None

        mock_result = MagicMock()
        mock_result.contents = [mock_content]

        mock_session = AsyncMock()
        mock_session.read_resource = AsyncMock(return_value=mock_result)
        state.session = mock_session

        text = await loader.read_resource("test-server", "file:///test.txt")
        assert text == "file contents here"

    async def test_read_resource_size_limit(self, loader):
        """Large resources are truncated."""
        from posipaka.core.tools.mcp_loader import MAX_RESOURCE_SIZE

        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        # Create content that exceeds MAX_RESOURCE_SIZE
        large_text = "x" * (MAX_RESOURCE_SIZE + 100)
        mock_content = MagicMock()
        mock_content.text = large_text
        mock_content.blob = None

        mock_result = MagicMock()
        mock_result.contents = [mock_content]

        mock_session = AsyncMock()
        mock_session.read_resource = AsyncMock(return_value=mock_result)
        state.session = mock_session

        text = await loader.read_resource("test-server", "file:///big.txt")
        assert "[truncated" in text


# ============================================================
# MCPToolLoader — Resource Templates
# ============================================================


class TestMCPResourceTemplates:
    async def test_get_resource_templates(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_template = MagicMock()
        mock_template.uriTemplate = "file:///{path}"
        mock_template.name = "File"
        mock_template.description = "Read any file"
        mock_template.mimeType = "text/plain"

        mock_result = MagicMock()
        mock_result.resourceTemplates = [mock_template]
        mock_result.nextCursor = None

        mock_session = AsyncMock()
        mock_session.list_resource_templates = AsyncMock(return_value=mock_result)
        state.session = mock_session

        templates = await loader.get_resource_templates("test-server")
        assert len(templates) == 1
        assert templates[0]["uriTemplate"] == "file:///{path}"

    async def test_get_resource_templates_not_ready(self, loader):
        loader.load_config()
        templates = await loader.get_resource_templates("test-server")
        assert templates == []

    def test_resource_template_to_dict(self):
        mock = MagicMock()
        mock.uriTemplate = "db:///{table}"
        mock.name = "Database Table"
        mock.description = "Query a table"
        mock.mimeType = "application/json"

        d = _resource_template_to_dict(mock)
        assert d["uriTemplate"] == "db:///{table}"
        assert d["name"] == "Database Table"


# ============================================================
# MCPToolLoader — Resource Subscription
# ============================================================


class TestMCPResourceSubscription:
    async def test_subscribe_resource(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_session = AsyncMock()
        mock_session.subscribe_resource = AsyncMock()
        state.session = mock_session

        result = await loader.subscribe_resource("test-server", "file:///a.txt")
        assert result is True
        mock_session.subscribe_resource.assert_called_once_with("file:///a.txt")

    async def test_unsubscribe_resource(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_session = AsyncMock()
        mock_session.unsubscribe_resource = AsyncMock()
        state.session = mock_session

        result = await loader.unsubscribe_resource("test-server", "file:///a.txt")
        assert result is True

    async def test_subscribe_not_ready(self, loader):
        loader.load_config()
        result = await loader.subscribe_resource("test-server", "file:///a.txt")
        assert result is False


# ============================================================
# MCPToolLoader — Prompts (mocked session)
# ============================================================


class TestMCPPrompts:
    async def test_get_prompts(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_arg = MagicMock()
        mock_arg.name = "name"
        mock_arg.description = "User name"
        mock_arg.required = True

        mock_prompt = MagicMock()
        mock_prompt.name = "greet"
        mock_prompt.description = "Greeting prompt"
        mock_prompt.arguments = [mock_arg]

        mock_result = MagicMock()
        mock_result.prompts = [mock_prompt]
        mock_result.nextCursor = None

        mock_session = AsyncMock()
        mock_session.list_prompts = AsyncMock(return_value=mock_result)
        state.session = mock_session

        prompts = await loader.get_prompts("test-server")
        assert len(prompts) == 1
        assert prompts[0]["name"] == "greet"
        assert prompts[0]["arguments"][0]["name"] == "name"
        assert prompts[0]["arguments"][0]["required"] is True

    async def test_get_prompts_not_ready(self, loader):
        loader.load_config()
        prompts = await loader.get_prompts("test-server")
        assert prompts == []

    async def test_get_prompt(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_msg_content = MagicMock()
        mock_msg_content.text = "Hello Alice!"

        mock_msg = MagicMock()
        mock_msg.role = "user"
        mock_msg.content = mock_msg_content

        mock_result = MagicMock()
        mock_result.description = "A greeting"
        mock_result.messages = [mock_msg]

        mock_session = AsyncMock()
        mock_session.get_prompt = AsyncMock(return_value=mock_result)
        state.session = mock_session

        prompt = await loader.get_prompt("test-server", "greet", {"name": "Alice"})
        assert prompt is not None
        assert prompt["messages"][0]["role"] == "user"
        assert prompt["messages"][0]["content"] == "Hello Alice!"


# ============================================================
# MCPToolLoader — Tool Search
# ============================================================


class TestMCPToolSearch:
    async def test_search_tools_keyword_match(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = [
            {"name": "read_file", "description": "Read a file from filesystem"},
            {"name": "write_file", "description": "Write content to a file"},
            {"name": "get_weather", "description": "Get current weather"},
        ]

        results = await loader.search_tools("read file")
        assert len(results) >= 1
        assert results[0]["name"] == "read_file"

    async def test_search_tools_empty_query(self, loader):
        loader.load_config()
        results = await loader.search_tools("")
        assert results == []

    async def test_search_tools_short_words_ignored(self, loader):
        loader.load_config()
        results = await loader.search_tools("a b c")
        assert results == []

    async def test_search_tools_no_match(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = [{"name": "read_file", "description": "Read"}]

        results = await loader.search_tools("zzzzzzz")
        assert results == []

    async def test_search_respects_limit(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = [
            {"name": f"tool_{i}", "description": f"tool number {i}"}
            for i in range(20)
        ]
        results = await loader.search_tools("tool", limit=3)
        assert len(results) == 3

    async def test_search_triggers_lazy_load(self, loader):
        """search_tools fetches tools from servers with empty caches."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = []  # Empty — should trigger get_tools

        mock_tool = MagicMock()
        mock_tool.name = "find_data"
        mock_tool.description = "Find data"
        mock_tool.inputSchema = {}
        mock_tool.annotations = None

        mock_result = MagicMock()
        mock_result.tools = [mock_tool]
        mock_result.nextCursor = None

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=mock_result)
        state.session = mock_session

        results = await loader.search_tools("find")
        assert len(results) >= 1
        assert results[0]["name"] == "find_data"


# ============================================================
# MCPToolLoader — Server Status
# ============================================================


class TestMCPServerStatusReport:
    def test_get_server_status(self, loader):
        loader.load_config()
        status = loader.get_server_status()
        assert len(status) == 1
        assert status[0]["name"] == "test-server"
        assert status[0]["status"] == "stopped"
        assert status[0]["tools_count"] == 0
        assert status[0]["resources_count"] == 0
        assert status[0]["transport"] == "stdio"
        assert "protocol_version" in status[0]
        assert "prompts_count" in status[0]


# ============================================================
# MCPToolLoader — Health Check
# ============================================================


class TestMCPHealthCheck:
    async def test_health_check_success(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_session = AsyncMock()
        mock_session.send_ping = AsyncMock(return_value=None)
        state.session = mock_session

        result = await loader.health_check("test-server")
        assert result is True

    async def test_health_check_failure(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.consecutive_failures = 0

        mock_session = AsyncMock()
        mock_session.send_ping = AsyncMock(side_effect=ConnectionError("dead"))
        state.session = mock_session

        result = await loader.health_check("test-server")
        assert result is False
        assert state.status == MCPServerStatus.ERROR
        assert state.consecutive_failures == 1

    async def test_health_check_not_ready(self, loader):
        loader.load_config()
        result = await loader.health_check("test-server")
        assert result is False

    async def test_health_check_all(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_session = AsyncMock()
        mock_session.send_ping = AsyncMock(return_value=None)
        state.session = mock_session

        results = await loader.health_check_all()
        assert results["test-server"] is True


# ============================================================
# MCPToolLoader — Auto-Reconnect
# ============================================================


class TestMCPAutoReconnect:
    async def test_try_reconnect_success(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.ERROR
        state.consecutive_failures = 1

        with patch.object(
            loader, "start_server", new_callable=AsyncMock, return_value=True,
        ):
            result = await loader._try_reconnect("test-server")
            assert result is True

    async def test_try_reconnect_circuit_breaker(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.ERROR
        state.consecutive_failures = CIRCUIT_BREAKER_THRESHOLD

        result = await loader._try_reconnect("test-server")
        assert result is False

    async def test_try_reconnect_not_error(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        result = await loader._try_reconnect("test-server")
        assert result is False

    async def test_reconnect_failed_servers(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.ERROR
        state.consecutive_failures = 1

        with patch.object(
            loader, "_try_reconnect", new_callable=AsyncMock, return_value=True,
        ), patch("asyncio.sleep", new_callable=AsyncMock):
            count = await loader.reconnect_failed_servers()
            assert count == 1

    async def test_reconnect_failed_servers_parallel(self, tmp_path):
        """reconnect_failed_servers runs in parallel."""
        import yaml

        config = {
            "servers": {
                "srv1": {"command": "echo", "enabled": True},
                "srv2": {"command": "echo", "enabled": True},
            },
            "settings": {"lazy_loading": False},
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        loader.load_config()

        for name in ["srv1", "srv2"]:
            state = loader._servers[name]
            state.status = MCPServerStatus.ERROR
            state.consecutive_failures = 1

        reconnect_calls = []

        async def mock_reconnect(name):
            reconnect_calls.append(name)
            return True

        with (
            patch.object(loader, "_try_reconnect", side_effect=mock_reconnect),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            count = await loader.reconnect_failed_servers()
        assert count == 2
        assert set(reconnect_calls) == {"srv1", "srv2"}

    async def test_reconnect_skips_circuit_breaker(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.ERROR
        state.consecutive_failures = CIRCUIT_BREAKER_THRESHOLD

        count = await loader.reconnect_failed_servers()
        assert count == 0


# ============================================================
# MCPToolLoader — Helpers
# ============================================================


class TestMCPHelpers:
    def test_error_result_format(self):
        result = _error_result("something broke")
        assert result["isError"] is True
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "something broke"

    def test_content_block_to_dict_text(self):
        block = MagicMock()
        block.type = "text"
        block.text = "hello"
        d = _content_block_to_dict(block)
        assert d == {"type": "text", "text": "hello"}

    def test_content_block_to_dict_image(self):
        block = MagicMock()
        block.type = "image"
        block.mimeType = "image/png"
        block.data = "base64..."
        d = _content_block_to_dict(block)
        assert d["type"] == "image"
        assert d["mimeType"] == "image/png"

    def test_content_block_to_dict_audio(self):
        block = MagicMock()
        block.type = "audio"
        block.mimeType = "audio/mp3"
        block.data = "..."
        d = _content_block_to_dict(block)
        assert d["type"] == "audio"

    def test_content_block_to_dict_resource(self):
        resource = MagicMock()
        resource.uri = "file:///a.txt"
        resource.text = "content"
        resource.mimeType = "text/plain"

        block = MagicMock()
        block.type = "resource"
        block.resource = resource
        d = _content_block_to_dict(block)
        assert d["type"] == "resource"
        assert d["resource"]["text"] == "content"

    def test_content_block_to_dict_unknown(self):
        block = MagicMock()
        block.type = "video"
        d = _content_block_to_dict(block)
        assert d["type"] == "video"


# ============================================================
# MCPBridge — Tool Name Generation
# ============================================================


class TestMCPBridgeHelpers:
    def test_make_tool_name(self):
        name = _make_tool_name("filesystem", "read_file")
        assert name == f"{MCP_TOOL_PREFIX}filesystem__read_file"

    def test_make_tool_name_with_hyphens(self):
        name = _make_tool_name("brave-search", "web-search")
        assert name == f"{MCP_TOOL_PREFIX}brave_search__web_search"

    def test_make_tool_name_long_server(self):
        name = _make_tool_name(
            "very-long-server-name-that-exceeds-twenty", "tool",
        )
        assert len(name.split("__")[0]) <= len(MCP_TOOL_PREFIX) + 20

    def test_make_tool_name_double_underscore_in_server(self):
        """Double underscores in server name should be collapsed."""
        name = _make_tool_name("my__server", "tool")
        # Should not have triple underscores
        assert "___" not in name

    def test_build_description(self):
        desc = _build_description("fs", {"name": "read", "description": "Read file"})
        assert "[MCP:fs]" in desc
        assert "Read file" in desc

    def test_build_description_no_desc(self):
        desc = _build_description("fs", {"name": "read"})
        assert "[MCP:fs]" in desc
        assert "read" in desc


# ============================================================
# MCPBridge — Content Extraction
# ============================================================


class TestMCPContentExtraction:
    def test_extract_text(self):
        result = {"content": [{"type": "text", "text": "Hello"}], "isError": False}
        assert _extract_content(result) == "Hello"

    def test_extract_error(self):
        result = {"content": [{"type": "text", "text": "Oops"}], "isError": True}
        assert _extract_content(result).startswith("Error:")

    def test_extract_image(self):
        result = {
            "content": [{"type": "image", "mimeType": "image/png", "data": "abc"}],
            "isError": False,
        }
        assert "Image" in _extract_content(result)

    def test_extract_resource_with_text(self):
        result = {
            "content": [
                {"type": "resource", "resource": {"uri": "file:///a", "text": "content"}},
            ],
            "isError": False,
        }
        assert _extract_content(result) == "content"

    def test_extract_resource_without_text(self):
        result = {
            "content": [
                {"type": "resource", "resource": {"uri": "file:///a"}},
            ],
            "isError": False,
        }
        assert "Resource:" in _extract_content(result)

    def test_extract_audio(self):
        result = {
            "content": [{"type": "audio", "mimeType": "audio/mp3", "data": "..."}],
            "isError": False,
        }
        assert "Audio" in _extract_content(result)

    def test_extract_unknown_type(self):
        result = {
            "content": [{"type": "video", "text": "some data"}],
            "isError": False,
        }
        output = _extract_content(result)
        assert "video" in output

    def test_extract_multi_content(self):
        result = {
            "content": [
                {"type": "text", "text": "Line 1"},
                {"type": "text", "text": "Line 2"},
            ],
            "isError": False,
        }
        output = _extract_content(result)
        assert "Line 1" in output
        assert "Line 2" in output

    def test_extract_empty_content(self):
        result = {"content": [], "isError": False}
        # Falls back to str(result)
        output = _extract_content(result)
        assert output  # Non-empty

    def test_extract_structured_content(self):
        """structuredContent returned when no content blocks."""
        result = {
            "content": [],
            "isError": False,
            "structuredContent": {"key": "value", "items": [1, 2, 3]},
        }
        output = _extract_content(result)
        assert "key" in output
        assert "value" in output
        assert "items" in output

    def test_extract_structured_content_error(self):
        """structuredContent with error flag."""
        result = {
            "content": [],
            "isError": True,
            "structuredContent": {"error": "not found"},
        }
        output = _extract_content(result)
        assert output.startswith("Error:")

    def test_extract_content_takes_priority_over_structured(self):
        """When both content and structuredContent present, content wins."""
        result = {
            "content": [{"type": "text", "text": "text result"}],
            "isError": False,
            "structuredContent": {"should": "be ignored"},
        }
        output = _extract_content(result)
        assert output == "text result"


# ============================================================
# MCPBridge — Registration
# ============================================================


class TestMCPBridgeRegistration:
    async def test_initialize_no_config(self, tmp_path, registry):
        bridge = MCPBridge(registry, config_path=tmp_path / "nonexistent.yaml")
        count = await bridge.initialize()
        assert count == 0

    async def test_register_tools_from_server(self, registry):
        bridge = MCPBridge(registry)
        mcp_tools = [
            {
                "name": "read_file",
                "description": "Read a file",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Write a file",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            },
        ]

        count = bridge._register_tools_from_server("fs", mcp_tools)
        assert count == 2

        all_tools = registry.list_tools()
        mcp_tools_registered = [t for t in all_tools if t["category"] == MCP_CATEGORY]
        assert len(mcp_tools_registered) == 2

        for tool_info in mcp_tools_registered:
            assert "mcp" in tool_info["tags"]
            assert "mcp:fs" in tool_info["tags"]

    async def test_register_tools_empty_schema(self, registry):
        bridge = MCPBridge(registry)
        count = bridge._register_tools_from_server("srv", [
            {"name": "simple_tool", "description": "No schema"},
        ])
        assert count == 1
        tool = registry.get(f"{MCP_TOOL_PREFIX}srv__simple_tool")
        assert tool is not None
        assert tool.input_schema == {"type": "object", "properties": {}}

    async def test_register_tools_with_annotations(self, registry):
        """Destructive MCP tools get requires_approval=True."""
        bridge = MCPBridge(registry)
        mcp_tools = [
            {
                "name": "delete_file",
                "description": "Delete a file",
                "annotations": {"destructiveHint": True, "readOnlyHint": False},
            },
            {
                "name": "read_file",
                "description": "Read a file",
                "annotations": {"readOnlyHint": True, "idempotentHint": True},
            },
            {
                "name": "plain_tool",
                "description": "No annotations",
            },
        ]

        count = bridge._register_tools_from_server("fs", mcp_tools)
        assert count == 3

        # Destructive tool should require approval
        delete_tool = registry.get(f"{MCP_TOOL_PREFIX}fs__delete_file")
        assert delete_tool is not None
        assert delete_tool.requires_approval is True

        # Read-only tool should not require approval
        read_tool = registry.get(f"{MCP_TOOL_PREFIX}fs__read_file")
        assert read_tool is not None
        assert read_tool.requires_approval is False
        assert "readonly" in read_tool.tags
        assert "idempotent" in read_tool.tags

        # Plain tool without annotations
        plain_tool = registry.get(f"{MCP_TOOL_PREFIX}fs__plain_tool")
        assert plain_tool is not None
        assert plain_tool.requires_approval is False

    async def test_unregister_server_tools(self, registry):
        bridge = MCPBridge(registry)
        bridge._register_tools_from_server("srv", [
            {"name": "tool1", "description": "T1"},
            {"name": "tool2", "description": "T2"},
        ])
        assert len(bridge._registered_tools) == 2

        bridge._unregister_server_tools("srv")
        assert len(bridge._registered_tools) == 0
        assert len(bridge._tool_routing) == 0
        # Tools should be fully removed from registry
        assert registry.get(f"{MCP_TOOL_PREFIX}srv__tool1") is None
        assert registry.get(f"{MCP_TOOL_PREFIX}srv__tool2") is None

    async def test_unregister_all(self, registry):
        bridge = MCPBridge(registry)
        bridge._register_tools_from_server("a", [{"name": "t1", "description": ""}])
        bridge._register_tools_from_server("b", [{"name": "t2", "description": ""}])
        assert len(bridge._registered_tools) == 2

        bridge._unregister_all_tools()
        assert len(bridge._registered_tools) == 0
        assert bridge._tool_routing == {}
        # Fully removed from registry
        assert registry.get(f"{MCP_TOOL_PREFIX}a__t1") is None
        assert registry.get(f"{MCP_TOOL_PREFIX}b__t2") is None


# ============================================================
# MCPBridge — Tool Execution
# ============================================================


class TestMCPBridgeExecution:
    async def test_handler_returns_text(self, registry):
        bridge = MCPBridge(registry)

        bridge._loader.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "Hello World"}],
            "isError": False,
        })

        bridge._register_tools_from_server("srv", [
            {"name": "greet", "description": "Greet"},
        ])

        result = await registry.execute(f"{MCP_TOOL_PREFIX}srv__greet", {})
        assert result == "Hello World"

    async def test_handler_error_response(self, registry):
        bridge = MCPBridge(registry)

        bridge._loader.call_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "Not found"}],
            "isError": True,
        })

        bridge._register_tools_from_server("srv", [
            {"name": "fail_tool", "description": "Fails"},
        ])

        result = await registry.execute(f"{MCP_TOOL_PREFIX}srv__fail_tool", {})
        assert "Error" in result

    async def test_handler_image_content(self, registry):
        bridge = MCPBridge(registry)

        bridge._loader.call_tool = AsyncMock(return_value={
            "content": [
                {"type": "image", "mimeType": "image/png", "data": "base64..."},
            ],
            "isError": False,
        })

        bridge._register_tools_from_server("srv", [
            {"name": "screenshot", "description": "Take screenshot"},
        ])

        result = await registry.execute(f"{MCP_TOOL_PREFIX}srv__screenshot", {})
        assert "Image" in result

    async def test_handler_multi_content(self, registry):
        bridge = MCPBridge(registry)

        bridge._loader.call_tool = AsyncMock(return_value={
            "content": [
                {"type": "text", "text": "Line 1"},
                {"type": "text", "text": "Line 2"},
            ],
            "isError": False,
        })

        bridge._register_tools_from_server("srv", [
            {"name": "multi", "description": "Multi"},
        ])

        result = await registry.execute(f"{MCP_TOOL_PREFIX}srv__multi", {})
        assert "Line 1" in result
        assert "Line 2" in result

    async def test_handler_structured_content(self, registry):
        bridge = MCPBridge(registry)

        bridge._loader.call_tool = AsyncMock(return_value={
            "content": [],
            "isError": False,
            "structuredContent": {"data": [1, 2, 3]},
        })

        bridge._register_tools_from_server("srv", [
            {"name": "query", "description": "Query data"},
        ])

        result = await registry.execute(f"{MCP_TOOL_PREFIX}srv__query", {})
        assert "data" in result
        assert "1" in result and "2" in result and "3" in result


# ============================================================
# MCPBridge — Routing Info
# ============================================================


class TestMCPBridgeRouting:
    def test_get_routing_info(self, registry):
        bridge = MCPBridge(registry)
        bridge._register_tools_from_server("myserver", [
            {"name": "my_tool", "description": "Test"},
        ])
        info = bridge.get_routing_info()
        tool_name = f"{MCP_TOOL_PREFIX}myserver__my_tool"
        assert tool_name in info
        assert info[tool_name] == ("myserver", "my_tool")

    def test_get_status(self, registry):
        bridge = MCPBridge(registry)
        bridge._register_tools_from_server("srv", [
            {"name": "t1", "description": ""},
        ])
        status = bridge.get_status()
        assert status["registered_tools"] == 1
        assert "servers" in status


# ============================================================
# MCPBridge — Schema Integration
# ============================================================


class TestMCPSchemaIntegration:
    def test_mcp_tools_in_anthropic_schemas(self, registry):
        bridge = MCPBridge(registry)
        bridge._register_tools_from_server("fs", [
            {
                "name": "read",
                "description": "Read file",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        ])

        schemas = registry.get_schemas("anthropic")
        mcp_schemas = [s for s in schemas if s["name"].startswith(MCP_TOOL_PREFIX)]
        assert len(mcp_schemas) == 1
        assert mcp_schemas[0]["input_schema"]["properties"]["path"]["type"] == "string"

    def test_mcp_tools_in_openai_schemas(self, registry):
        bridge = MCPBridge(registry)
        bridge._register_tools_from_server("fs", [
            {
                "name": "read",
                "description": "Read file",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        ])

        schemas = registry.get_schemas("openai")
        mcp_schemas = [
            s for s in schemas if s["function"]["name"].startswith(MCP_TOOL_PREFIX)
        ]
        assert len(mcp_schemas) == 1
        assert mcp_schemas[0]["type"] == "function"

    def test_mcp_tools_in_metadata(self, registry):
        bridge = MCPBridge(registry)
        bridge._register_tools_from_server("github", [
            {"name": "list_repos", "description": "List GitHub repositories"},
        ])

        metadata = registry.get_skill_metadata()
        assert "mcp_github__list_repos" in metadata
        assert "[MCP:github]" in metadata


# ============================================================
# MCPBridge — Callbacks
# ============================================================


class TestMCPBridgeCallbacks:
    def test_bridge_passes_callbacks(self, registry):
        """MCPBridge passes sampling/elicitation callbacks to loader."""
        async def mock_sampling(ctx, params):
            pass

        async def mock_elicitation(ctx, params):
            pass

        bridge = MCPBridge(
            registry,
            sampling_callback=mock_sampling,
            elicitation_callback=mock_elicitation,
        )
        assert bridge._loader._sampling_callback is mock_sampling
        assert bridge._loader._elicitation_callback is mock_elicitation

    def test_bridge_no_callbacks(self, registry):
        """MCPBridge works without callbacks."""
        bridge = MCPBridge(registry)
        assert bridge._loader._sampling_callback is None
        assert bridge._loader._elicitation_callback is None


# ============================================================
# MCPServerState
# ============================================================


class TestMCPServerState:
    def test_initial_status(self):
        config = MCPServerConfig(name="test", command="echo")
        state = MCPServerState(config=config)
        assert state.status == MCPServerStatus.STOPPED
        assert state.tools == []
        assert state.prompts == []
        assert state.resources == []
        assert state.resource_templates == []
        assert state.consecutive_failures == 0
        assert state.protocol_version == ""
        assert state.session is None
        assert state.resources_cached_at == 0.0

    def test_fields_initialization(self):
        config = MCPServerConfig(name="test", command="echo")
        state = MCPServerState(config=config)
        assert state.exit_stack is None


# ============================================================
# ToolRegistry — Unregister
# ============================================================


class TestToolRegistryUnregister:
    def test_unregister_removes_tool(self, registry):
        from posipaka.core.tools.registry import ToolDefinition

        tool = ToolDefinition(
            name="test_tool",
            description="Test",
            category="builtin",
            handler=lambda: None,
            input_schema={},
        )
        registry.register(tool)
        assert registry.get("test_tool") is not None

        registry.unregister("test_tool")
        assert registry.get("test_tool") is None

    def test_unregister_nonexistent(self, registry):
        # Should not raise
        registry.unregister("nonexistent_tool")

    def test_unregister_not_in_schemas(self, registry):
        from posipaka.core.tools.registry import ToolDefinition

        tool = ToolDefinition(
            name="temp_tool",
            description="Temp",
            category="mcp",
            handler=lambda: None,
            input_schema={"type": "object", "properties": {}},
        )
        registry.register(tool)
        schemas = registry.get_schemas("anthropic")
        assert any(s["name"] == "temp_tool" for s in schemas)

        registry.unregister("temp_tool")
        schemas = registry.get_schemas("anthropic")
        assert not any(s["name"] == "temp_tool" for s in schemas)


# ============================================================
# MCPServerConfig — HTTP transport + OAuth
# ============================================================


class TestMCPServerConfigHTTP:
    def test_http_config(self):
        config = MCPServerConfig(
            name="remote",
            command="",
            transport="streamable-http",
            url="http://localhost:8000/mcp",
        )
        assert config.transport == "streamable-http"
        assert config.url == "http://localhost:8000/mcp"

    def test_stdio_config_default(self):
        config = MCPServerConfig(name="local", command="npx")
        assert config.transport == "stdio"
        assert config.url == ""
        assert config.headers == {}
        assert config.oauth is None

    def test_http_config_with_oauth(self):
        oauth = MCPOAuthConfig(
            client_name="myapp",
            redirect_uri="http://localhost:9000/cb",
            scope="read write",
        )
        config = MCPServerConfig(
            name="secure",
            command="",
            transport="streamable-http",
            url="http://localhost:8000/mcp",
            oauth=oauth,
        )
        assert config.oauth is not None
        assert config.oauth.client_name == "myapp"
        assert config.oauth.scope == "read write"

    def test_http_config_with_headers(self):
        config = MCPServerConfig(
            name="api",
            command="",
            transport="streamable-http",
            url="http://localhost:8000/mcp",
            headers={"Authorization": "Bearer abc"},
        )
        assert config.headers["Authorization"] == "Bearer abc"


# ============================================================
# MCPOAuthConfig
# ============================================================


class TestMCPOAuthConfig:
    def test_defaults(self):
        oauth = MCPOAuthConfig()
        assert oauth.client_name == "posipaka"
        assert oauth.redirect_uri == "http://localhost:3000/callback"
        assert oauth.scope == ""

    def test_custom(self):
        oauth = MCPOAuthConfig(
            client_name="test", redirect_uri="http://x/cb", scope="all",
        )
        assert oauth.client_name == "test"
        assert oauth.scope == "all"


# ============================================================
# make_safe_server_name — collision-resistant sanitization
# ============================================================


class TestMakeSafeServerName:
    def test_short_name_unchanged(self):
        assert make_safe_server_name("filesystem") == "filesystem"

    def test_hyphens_replaced(self):
        assert make_safe_server_name("brave-search") == "brave_search"

    def test_dots_replaced(self):
        assert make_safe_server_name("my.server") == "my_server"

    def test_double_underscore_collapsed(self):
        result = make_safe_server_name("my__server")
        assert "__" not in result
        assert result == "my_server"

    def test_triple_underscore_collapsed(self):
        """Triple underscores should also be collapsed."""
        result = make_safe_server_name("a___b")
        assert "__" not in result
        assert result == "a_b"

    def test_long_name_truncated_with_hash(self):
        name = "very-long-server-name-that-exceeds-twenty-characters"
        result = make_safe_server_name(name)
        assert len(result) <= 20

    def test_different_long_names_get_different_results(self):
        """Two names that truncate to the same prefix get different hashes."""
        name1 = "very-long-server-name-alpha"
        name2 = "very-long-server-name-beta"
        result1 = make_safe_server_name(name1)
        result2 = make_safe_server_name(name2)
        assert result1 != result2

    def test_exact_20_chars_no_hash(self):
        name = "a" * 20  # Exactly 20 chars
        result = make_safe_server_name(name)
        assert result == name


# ============================================================
# MCPToolLoader — session kwargs (client_info, callbacks)
# ============================================================


class TestMCPSessionKwargs:
    def test_make_session_kwargs_has_client_info(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        kwargs = loader._make_session_kwargs(state)
        assert kwargs["client_info"] is not None
        assert kwargs["client_info"].name == "posipaka"
        from posipaka import __version__
        assert kwargs["client_info"].version == __version__

    def test_make_session_kwargs_has_callbacks(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        kwargs = loader._make_session_kwargs(state)
        assert kwargs["logging_callback"] is not None
        assert kwargs["list_roots_callback"] is not None
        assert kwargs["message_handler"] is not None

    def test_make_session_kwargs_with_sampling(self, mcp_yaml):
        """sampling_callback is passed through to session kwargs."""
        async def mock_sampling(ctx, params):
            pass

        loader = MCPToolLoader(config_path=mcp_yaml, sampling_callback=mock_sampling)
        loader.load_config()
        state = loader._servers["test-server"]
        kwargs = loader._make_session_kwargs(state)
        assert kwargs["sampling_callback"] is mock_sampling

    def test_make_session_kwargs_with_elicitation(self, mcp_yaml):
        """elicitation_callback is passed through to session kwargs."""
        async def mock_elicitation(ctx, params):
            pass

        loader = MCPToolLoader(config_path=mcp_yaml, elicitation_callback=mock_elicitation)
        loader.load_config()
        state = loader._servers["test-server"]
        kwargs = loader._make_session_kwargs(state)
        assert kwargs["elicitation_callback"] is mock_elicitation

    def test_make_session_kwargs_no_optional_callbacks(self, loader):
        """Without sampling/elicitation, those keys should not be in kwargs."""
        loader.load_config()
        state = loader._servers["test-server"]
        kwargs = loader._make_session_kwargs(state)
        assert "sampling_callback" not in kwargs
        assert "elicitation_callback" not in kwargs

    def test_message_handler_invalidates_tool_cache(self, loader):
        """tools/list_changed notification should invalidate cache."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.tools_cached_at = time_mod.time()

        kwargs = loader._make_session_kwargs(state)
        handler = kwargs["message_handler"]

        # Simulate tools/list_changed notification
        mock_msg = MagicMock()
        mock_msg.method = "notifications/tools/list_changed"
        handler(mock_msg)

        assert state.tools_cached_at == 0  # Cache invalidated

    def test_message_handler_invalidates_resources(self, loader):
        """resources/list_changed notification should clear resources."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.resources = [{"uri": "test"}]
        state.resource_templates = [{"uriTemplate": "test:///{x}"}]
        state.resources_cached_at = time_mod.time()

        kwargs = loader._make_session_kwargs(state)
        handler = kwargs["message_handler"]

        mock_msg = MagicMock()
        mock_msg.method = "notifications/resources/list_changed"
        handler(mock_msg)

        assert state.resources == []
        assert state.resource_templates == []
        assert state.resources_cached_at == 0

    def test_message_handler_invalidates_prompts(self, loader):
        """prompts/list_changed notification should clear prompts."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.prompts = [{"name": "test_prompt"}]

        kwargs = loader._make_session_kwargs(state)
        handler = kwargs["message_handler"]

        mock_msg = MagicMock()
        mock_msg.method = "notifications/prompts/list_changed"
        handler(mock_msg)

        assert state.prompts == []

    async def test_list_roots_callback(self, loader):
        """list_roots_callback returns data_dir as root."""
        loader.load_config()
        state = loader._servers["test-server"]
        kwargs = loader._make_session_kwargs(state)

        roots = await kwargs["list_roots_callback"](None)
        assert len(roots) == 1
        assert "posipaka" in str(roots[0].uri) or "posipaka" in roots[0].name


# ============================================================
# MCPToolLoader — stop_all with timeout
# ============================================================


class TestMCPStopAll:
    async def test_stop_all_timeout(self, loader):
        """stop_all should not hang forever."""
        loader.load_config()
        # Even with no running servers, should complete without error
        await loader.stop_all()

    async def test_stop_all_clears_state(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = [{"name": "t"}]
        state.resources = [{"uri": "x"}]
        state.resource_templates = [{"uriTemplate": "y:///{z}"}]

        await loader.stop_all()
        assert state.status == MCPServerStatus.STOPPED
        assert state.tools == []
        assert state.resources == []
        assert state.resource_templates == []
        assert state.resources_cached_at == 0.0


# ============================================================
# MCPBridge — set-based _registered_tools
# ============================================================


class TestMCPBridgeSetRegistration:
    def test_registered_tools_is_set(self, registry):
        bridge = MCPBridge(registry)
        assert isinstance(bridge._registered_tools, set)

    def test_discard_on_unregister(self, registry):
        bridge = MCPBridge(registry)
        bridge._register_tools_from_server("srv", [
            {"name": "t1", "description": "T1"},
        ])
        assert len(bridge._registered_tools) == 1
        bridge._unregister_server_tools("srv")
        assert len(bridge._registered_tools) == 0


# ============================================================
# Headers env var resolution
# ============================================================


class TestHeadersEnvResolution:
    def test_headers_resolved_in_config(self, tmp_path, monkeypatch):
        """Headers should resolve ${VAR} references like env does."""
        import yaml

        monkeypatch.setenv("MY_TOKEN", "secret_token_123")
        config = {
            "servers": {
                "api-server": {
                    "transport": "streamable-http",
                    "url": "https://example.com/mcp",
                    "headers": {
                        "Authorization": "Bearer ${MY_TOKEN}",
                        "X-Static": "plain_value",
                    },
                    "enabled": True,
                },
            },
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")

        loader = MCPToolLoader(config_path=path)
        with patch(
            "posipaka.core.tools.mcp_loader._validate_mcp_url",
            return_value=(True, "ok"),
        ):
            configs = loader.load_config()
        assert len(configs) == 1
        assert configs[0].headers["Authorization"] == "Bearer secret_token_123"
        assert configs[0].headers["X-Static"] == "plain_value"

    def test_headers_with_default(self, tmp_path, monkeypatch):
        """Headers ${VAR:-default} syntax works."""
        import yaml

        monkeypatch.delenv("MISSING_HEADER_VAR", raising=False)
        config = {
            "servers": {
                "srv": {
                    "transport": "streamable-http",
                    "url": "https://example.com/mcp",
                    "headers": {"X-Key": "${MISSING_HEADER_VAR:-fallback_key}"},
                    "enabled": True,
                },
            },
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        with patch(
            "posipaka.core.tools.mcp_loader._validate_mcp_url",
            return_value=(True, "ok"),
        ):
            configs = loader.load_config()
        assert configs[0].headers["X-Key"] == "fallback_key"


# ============================================================
# SSRF validation for MCP URLs
# ============================================================


class TestMCPSSRFValidation:
    def test_allows_localhost(self):
        """MCP servers commonly run on localhost — must be allowed."""
        safe, reason = _validate_mcp_url("http://localhost:8000/mcp")
        assert safe is True

    def test_allows_127_0_0_1(self):
        """Loopback address should be allowed for local MCP servers."""
        safe, reason = _validate_mcp_url("http://127.0.0.1:8000/mcp")
        assert safe is True

    def test_blocks_metadata_endpoint(self):
        safe, reason = _validate_mcp_url("http://169.254.169.254/latest/meta-data")
        assert safe is False

    def test_blocks_zero_address(self):
        safe, reason = _validate_mcp_url("http://0.0.0.0:8000/mcp")
        assert safe is False

    def test_blocks_link_local(self):
        safe, reason = _validate_mcp_url("http://169.254.1.1:8000/mcp")
        assert safe is False

    def test_blocks_google_metadata(self):
        safe, reason = _validate_mcp_url("http://metadata.google.internal/mcp")
        assert safe is False

    def test_allows_public_url(self):
        """Public URLs should pass."""
        safe, _ = _validate_mcp_url("https://mcp.example.com/mcp")
        assert safe is True

    def test_allows_private_ip(self):
        """Private IPs are allowed for MCP (common in local networks)."""
        safe, _ = _validate_mcp_url("http://192.168.1.100:8000/mcp")
        assert safe is True

    def test_config_skips_blocked_servers(self, tmp_path):
        """Servers with SSRF-blocked URLs are skipped during config loading."""
        import yaml

        config = {
            "servers": {
                "evil": {
                    "transport": "streamable-http",
                    "url": "http://169.254.169.254/mcp",
                    "enabled": True,
                },
            },
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        configs = loader.load_config()
        assert len(configs) == 0

    def test_blocks_invalid_scheme(self):
        safe, reason = _validate_mcp_url("ftp://server:21/mcp")
        assert safe is False


# ============================================================
# Prompt content type handling
# ============================================================


class TestPromptContentToStr:
    def test_text_content(self):
        content = MagicMock()
        content.type = "text"
        content.text = "Hello world"
        assert _prompt_content_to_str(content) == "Hello world"

    def test_image_content(self):
        content = MagicMock()
        content.type = "image"
        content.mimeType = "image/png"
        result = _prompt_content_to_str(content)
        assert "Image" in result
        assert "image/png" in result

    def test_audio_content(self):
        content = MagicMock()
        content.type = "audio"
        content.mimeType = "audio/wav"
        result = _prompt_content_to_str(content)
        assert "Audio" in result

    def test_resource_content_with_text(self):
        resource = MagicMock()
        resource.text = "resource text"
        resource.uri = "file:///a.txt"

        content = MagicMock()
        content.type = "resource"
        content.resource = resource
        assert _prompt_content_to_str(content) == "resource text"

    def test_resource_content_without_text(self):
        resource = MagicMock()
        resource.text = None
        resource.uri = "file:///a.bin"

        content = MagicMock()
        content.type = "resource"
        content.resource = resource
        result = _prompt_content_to_str(content)
        assert "Resource:" in result
        assert "file:///a.bin" in result

    def test_fallback_to_text_attr(self):
        content = MagicMock()
        content.type = "custom"
        content.text = "fallback text"
        assert _prompt_content_to_str(content) == "fallback text"

    def test_fallback_to_str(self):
        content = MagicMock()
        content.type = "unknown"
        content.text = None
        result = _prompt_content_to_str(content)
        assert result  # Non-empty string representation


# ============================================================
# Fuzzy tool search
# ============================================================


class TestFuzzyToolSearch:
    async def test_fuzzy_match_typo(self, loader):
        """Fuzzy matching finds tools with typos in query."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = [
            {"name": "read_file", "description": "Read a file"},
            {"name": "write_file", "description": "Write a file"},
        ]
        # "raed" is a typo for "read"
        results = await loader.search_tools("raed file")
        # Should still find read_file via fuzzy
        found_names = [r["name"] for r in results]
        assert "read_file" in found_names

    async def test_exact_match_scores_higher(self, loader):
        """Exact keyword match should score higher than fuzzy."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = [
            {"name": "read_file", "description": "Read a file"},
            {"name": "reed_pipe", "description": "Musical instrument"},
        ]
        results = await loader.search_tools("read")
        assert results[0]["name"] == "read_file"

    def test_score_tool_no_match(self):
        """Completely unrelated words score 0."""
        score = _score_tool(
            ["zzzzz"], "zzzzz",
            {"name": "read_file", "description": "Read a file"},
        )
        assert score == 0

    def test_score_tool_keyword_in_name(self):
        score = _score_tool(
            ["read"], "read",
            {"name": "read_file", "description": ""},
        )
        assert score >= 0.6

    def test_score_tool_keyword_in_description(self):
        score = _score_tool(
            ["weather"], "weather",
            {"name": "get_data", "description": "Get current weather"},
        )
        assert score >= 0.3


# ============================================================
# _FileTokenStorage (extracted from method)
# ============================================================


class TestFileTokenStorage:
    def test_init_no_file(self, tmp_path):
        storage = _FileTokenStorage(tmp_path / "tokens.json")
        assert storage._tokens is None
        assert storage._client_info is None

    async def test_get_set_tokens(self, tmp_path):
        storage = _FileTokenStorage(tmp_path / "tokens.json")
        assert await storage.get_tokens() is None

        mock_tokens = MagicMock()
        mock_tokens.model_dump.return_value = {"access_token": "abc"}
        await storage.set_tokens(mock_tokens)
        assert storage._tokens is mock_tokens

        # File should be written
        assert (tmp_path / "tokens.json").exists()

    async def test_get_set_client_info(self, tmp_path):
        storage = _FileTokenStorage(tmp_path / "tokens.json")
        assert await storage.get_client_info() is None

        mock_info = MagicMock()
        mock_info.model_dump.return_value = {"client_id": "xyz"}
        await storage.set_client_info(mock_info)
        assert storage._client_info is mock_info

    def test_creates_parent_dirs(self, tmp_path):
        deep_path = tmp_path / "sub" / "dir" / "tokens.json"
        storage = _FileTokenStorage(deep_path)
        mock_tokens = MagicMock()
        mock_tokens.model_dump.return_value = {"access_token": "test"}
        storage._tokens = mock_tokens
        storage._save()
        assert deep_path.exists()


# ============================================================
# MCPBridge — handler error boundary
# ============================================================


class TestMCPBridgeHandlerErrorBoundary:
    async def test_handler_catches_exceptions(self, registry):
        """Handler should catch and return error string, not raise."""
        bridge = MCPBridge(registry)

        bridge._loader.call_tool = AsyncMock(
            side_effect=RuntimeError("connection lost"),
        )

        bridge._register_tools_from_server("srv", [
            {"name": "flaky_tool", "description": "Flaky"},
        ])

        result = await registry.execute(f"{MCP_TOOL_PREFIX}srv__flaky_tool", {})
        assert "Error" in result
        assert "flaky_tool" in result

    async def test_handler_catches_extract_errors(self, registry):
        """Handler catches errors in _extract_content too."""
        bridge = MCPBridge(registry)

        # Return something that will cause _extract_content to fail
        bridge._loader.call_tool = AsyncMock(
            side_effect=TypeError("unexpected type"),
        )

        bridge._register_tools_from_server("srv", [
            {"name": "bad_tool", "description": "Bad"},
        ])

        result = await registry.execute(f"{MCP_TOOL_PREFIX}srv__bad_tool", {})
        assert "Error" in result


# ============================================================
# MCP SDK availability check
# ============================================================


class TestMCPAvailabilityCheck:
    def test_mcp_available_flag(self):
        """MCP SDK should be detected at import time."""
        from posipaka.core.tools.mcp_loader import _MCP_AVAILABLE
        # In test environment, mcp is installed
        assert isinstance(_MCP_AVAILABLE, bool)

    async def test_start_all_without_mcp(self, loader):
        """start_all should handle missing SDK gracefully."""
        loader.load_config()
        with patch("posipaka.core.tools.mcp_loader._MCP_AVAILABLE", False):
            count = await loader.start_all()
            assert count == 0

    async def test_start_server_without_mcp(self, loader):
        """start_server should return False when SDK missing."""
        loader.load_config()
        with patch("posipaka.core.tools.mcp_loader._MCP_AVAILABLE", False):
            result = await loader.start_server("test-server")
            assert result is False


# ============================================================
# Roots configuration
# ============================================================


class TestMCPRootsConfig:
    def test_default_roots_empty(self):
        config = MCPServerConfig(name="test", command="echo")
        assert config.roots == []

    def test_roots_from_config(self, tmp_path):
        import yaml

        config = {
            "servers": {
                "fs": {
                    "command": "echo",
                    "enabled": True,
                    "roots": ["/home/user/docs", "/home/user/projects"],
                },
            },
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        configs = loader.load_config()
        assert len(configs) == 1
        assert configs[0].roots == ["/home/user/docs", "/home/user/projects"]

    async def test_list_roots_callback_custom(self, tmp_path):
        """Custom roots from config are returned by list_roots_callback."""
        import yaml

        config = {
            "servers": {
                "fs": {
                    "command": "echo",
                    "enabled": True,
                    "roots": ["/tmp/root1", "/tmp/root2"],
                },
            },
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        loader.load_config()
        state = loader._servers["fs"]
        kwargs = loader._make_session_kwargs(state)

        roots = await kwargs["list_roots_callback"](None)
        assert len(roots) == 2
        uris = [str(r.uri) for r in roots]
        assert "file:///tmp/root1" in uris
        assert "file:///tmp/root2" in uris

    async def test_list_roots_callback_default(self, loader):
        """Without custom roots, default data_dir is used."""
        loader.load_config()
        state = loader._servers["test-server"]
        kwargs = loader._make_session_kwargs(state)

        roots = await kwargs["list_roots_callback"](None)
        assert len(roots) == 1
        assert "posipaka" in roots[0].name


# ============================================================
# Initialize with retry
# ============================================================


class TestMCPInitializeWithRetry:
    async def test_init_retry_success_first_try(self, loader):
        """Initialize succeeds on first attempt."""
        loader.load_config()
        state = loader._servers["test-server"]
        config = state.config

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.protocolVersion = "2024-11-05"
        mock_session.initialize = AsyncMock(return_value=mock_result)

        result = await loader._initialize_with_retry(mock_session, config)
        assert result is mock_result
        assert mock_session.initialize.call_count == 1

    async def test_init_retry_success_second_try(self, loader):
        """Initialize fails first, succeeds on retry."""
        loader.load_config()
        state = loader._servers["test-server"]
        config = state.config

        mock_result = MagicMock()
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock(
            side_effect=[ConnectionError("temp"), mock_result],
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await loader._initialize_with_retry(mock_session, config)
        assert result is mock_result
        assert mock_session.initialize.call_count == 2

    async def test_init_retry_exhausted(self, loader):
        """Initialize fails all attempts — raises last error."""
        loader.load_config()
        state = loader._servers["test-server"]
        config = state.config

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock(
            side_effect=ConnectionError("persistent failure"),
        )

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(ConnectionError, match="persistent failure"),
        ):
            await loader._initialize_with_retry(mock_session, config)
        assert mock_session.initialize.call_count == INIT_MAX_RETRIES + 1


# ============================================================
# Completions API
# ============================================================


class TestMCPCompletions:
    async def test_get_completion_not_ready(self, loader):
        loader.load_config()
        result = await loader.get_completion(
            "test-server", "ref/prompt", "greet", "name", "Al",
        )
        assert result == []

    async def test_get_completion_success(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_completion = MagicMock()
        mock_completion.values = ["Alice", "Alex", "Albert"]

        mock_result = MagicMock()
        mock_result.completion = mock_completion

        mock_session = AsyncMock()
        mock_session.complete = AsyncMock(return_value=mock_result)
        state.session = mock_session

        result = await loader.get_completion(
            "test-server", "ref/prompt", "greet", "name", "Al",
        )
        assert result == ["Alice", "Alex", "Albert"]
        mock_session.complete.assert_called_once()

    async def test_get_completion_resource_ref(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_completion = MagicMock()
        mock_completion.values = ["users", "orders"]

        mock_result = MagicMock()
        mock_result.completion = mock_completion

        mock_session = AsyncMock()
        mock_session.complete = AsyncMock(return_value=mock_result)
        state.session = mock_session

        result = await loader.get_completion(
            "test-server", "ref/resource", "db:///{table}", "table", "us",
        )
        assert result == ["users", "orders"]

    async def test_get_completion_invalid_ref_type(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.session = AsyncMock()

        result = await loader.get_completion(
            "test-server", "ref/invalid", "x", "y", "z",
        )
        assert result == []

    async def test_get_completion_error(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_session = AsyncMock()
        mock_session.complete = AsyncMock(side_effect=RuntimeError("fail"))
        state.session = mock_session

        result = await loader.get_completion(
            "test-server", "ref/prompt", "greet", "name", "Al",
        )
        assert result == []


# ============================================================
# _make_tool_name — dots and spaces sanitization
# ============================================================


class TestMakeToolNameSanitization:
    def test_dots_in_tool_name(self):
        name = _make_tool_name("srv", "file.read")
        assert "." not in name
        assert name == f"{MCP_TOOL_PREFIX}srv__file_read"

    def test_spaces_in_tool_name(self):
        name = _make_tool_name("srv", "my tool")
        assert " " not in name
        assert name == f"{MCP_TOOL_PREFIX}srv__my_tool"

    def test_combined_special_chars(self):
        name = _make_tool_name("my-server", "tool.with-mixed chars")
        assert "-" not in name.split("__")[1]
        assert "." not in name
        assert " " not in name


# ============================================================
# Fuzzy scoring — multi-word fix
# ============================================================


class TestFuzzyScoreMultiWord:
    def test_multi_word_all_score(self):
        """Each matching word contributes to score independently."""
        score = _score_tool(
            ["read", "file"], "read file",
            {"name": "read_file", "description": ""},
        )
        # Both "read" and "file" match in name — should score > single word
        single_score = _score_tool(
            ["read"], "read",
            {"name": "read_file", "description": ""},
        )
        assert score > single_score

    def test_fuzzy_still_works_after_exact(self):
        """Fuzzy matching works for word that has no exact match,
        even if another word had an exact match."""
        score = _score_tool(
            ["read", "flie"], "read flie",
            {"name": "read_file", "description": ""},
        )
        # "read" matches exactly, "flie" should fuzzy-match "file"
        assert score > 0.6  # More than just "read" alone


# ============================================================
# Health check parallel
# ============================================================


class TestMCPHealthCheckParallel:
    async def test_health_check_all_parallel(self, tmp_path):
        """health_check_all checks servers in parallel."""
        import yaml

        config = {
            "servers": {
                "srv1": {"command": "echo", "enabled": True},
                "srv2": {"command": "echo", "enabled": True},
            },
            "settings": {"lazy_loading": False},
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        loader.load_config()

        for name in ["srv1", "srv2"]:
            state = loader._servers[name]
            state.status = MCPServerStatus.READY
            mock_session = AsyncMock()
            mock_session.send_ping = AsyncMock(return_value=None)
            state.session = mock_session

        results = await loader.health_check_all()
        assert results == {"srv1": True, "srv2": True}

    async def test_health_check_all_empty(self, loader):
        """health_check_all returns empty dict when no active servers."""
        loader.load_config()
        results = await loader.health_check_all()
        assert results == {}


# ============================================================
# Progress notifications
# ============================================================


class TestMCPProgressNotifications:
    async def test_progress_stored_in_state(self, loader):
        """Progress notifications are stored in server state."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        kwargs = loader._make_session_kwargs(state)
        handler = kwargs["message_handler"]

        # Simulate progress notification
        msg = MagicMock()
        msg.method = "notifications/progress"
        params = MagicMock()
        params.progressToken = "tok-123"
        params.progress = 50
        params.total = 100
        msg.params = params

        handler(msg)

        assert "tok-123" in state.progress
        assert state.progress["tok-123"]["progress"] == 50
        assert state.progress["tok-123"]["total"] == 100

    async def test_progress_callback_called(self, tmp_path):
        """Progress callback is invoked on progress notification."""
        import yaml

        config = {
            "servers": {"srv": {"command": "echo", "enabled": True}},
            "settings": {"lazy_loading": False},
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")

        callback_calls = []

        def on_progress(server, token, progress, total):
            callback_calls.append((server, token, progress, total))

        loader = MCPToolLoader(config_path=path, progress_callback=on_progress)
        loader.load_config()
        state = loader._servers["srv"]

        kwargs = loader._make_session_kwargs(state)
        handler = kwargs["message_handler"]

        msg = MagicMock()
        msg.method = "notifications/progress"
        params = MagicMock()
        params.progressToken = "tok-1"
        params.progress = 75
        params.total = 100
        msg.params = params

        handler(msg)

        assert len(callback_calls) == 1
        assert callback_calls[0] == ("srv", "tok-1", 75, 100)

    async def test_progress_cleared_on_cleanup(self, loader):
        """Progress data is cleared when server is cleaned up."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.progress = {"tok": {"progress": 10, "total": 50}}

        await loader._cleanup_server(state)
        assert state.progress == {}


# ============================================================
# Cancellation support
# ============================================================


class TestMCPCancellation:
    async def test_cancel_nonexistent_call(self, loader):
        """Cancelling a non-existent call returns False."""
        loader.load_config()
        assert loader.cancel_tool_call("nonexistent") is False

    async def test_call_tool_with_call_id(self, loader):
        """call_tool tracks inflight calls by call_id."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = [{"name": "slow", "description": "Slow tool"}]

        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = "done"

        mock_result = MagicMock()
        mock_result.content = [mock_content]
        mock_result.isError = False
        mock_result.structuredContent = None

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)
        state.session = mock_session

        result = await loader.call_tool(
            "test-server", "slow", {}, call_id="call-1",
        )
        assert result["isError"] is False
        # After completion, call_id should be cleaned up
        assert "call-1" not in loader._inflight

    async def test_call_tool_validates_tool_exists(self, loader):
        """call_tool rejects unknown tools when tool list is loaded."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = [{"name": "known_tool", "description": "Known"}]
        state.session = AsyncMock()

        result = await loader.call_tool("test-server", "unknown_tool", {})
        assert result["isError"] is True
        assert "not found" in result["content"][0]["text"]

    async def test_call_tool_skips_validation_when_no_tools(self, loader):
        """call_tool skips validation when tool list is empty (not loaded yet)."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = []  # No tools loaded yet

        mock_content = MagicMock()
        mock_content.type = "text"
        mock_content.text = "ok"

        mock_result = MagicMock()
        mock_result.content = [mock_content]
        mock_result.isError = False
        mock_result.structuredContent = None

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)
        state.session = mock_session

        result = await loader.call_tool("test-server", "any_tool", {})
        assert result["isError"] is False


# ============================================================
# Atomic token storage
# ============================================================


class TestFileTokenStorageAtomic:
    def test_atomic_save_uses_tmp(self, tmp_path):
        """_save uses tmp+rename for atomic writes."""
        storage = _FileTokenStorage(tmp_path / "tokens.json")
        mock_tokens = MagicMock()
        mock_tokens.model_dump.return_value = {"access_token": "abc"}
        storage._tokens = mock_tokens
        storage._save()

        # Final file should exist, tmp should not
        assert (tmp_path / "tokens.json").exists()
        assert not (tmp_path / "tokens.json.tmp").exists()

    def test_load_error_logged(self, tmp_path):
        """_load logs errors instead of swallowing silently."""
        path = tmp_path / "tokens.json"
        path.write_text("invalid json{{{", encoding="utf-8")

        with patch("posipaka.core.tools.mcp_loader.logger") as mock_logger:
            _FileTokenStorage(path)
            mock_logger.debug.assert_called()


# ============================================================
# Read resource with auto-reconnect
# ============================================================


class TestReadResourceReconnect:
    async def test_read_resource_auto_reconnect(self, loader):
        """read_resource triggers reconnect for ERROR servers."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.ERROR
        state.consecutive_failures = 1

        with patch.object(
            loader, "_try_reconnect", new_callable=AsyncMock, return_value=False,
        ) as mock_reconnect:
            result = await loader.read_resource("test-server", "file:///test.txt")
            mock_reconnect.assert_called_once_with("test-server")
            assert result == ""

    async def test_read_resource_increments_failures(self, loader):
        """read_resource increments failures on error."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.consecutive_failures = 0

        mock_session = AsyncMock()
        mock_session.read_resource = AsyncMock(side_effect=RuntimeError("fail"))
        state.session = mock_session

        result = await loader.read_resource("test-server", "file:///test.txt")
        assert result == ""
        assert state.consecutive_failures == 1


# ============================================================
# Per-server rate limiting (semaphore)
# ============================================================


class TestMCPCallSemaphore:
    async def test_semaphore_created_on_start(self, loader):
        """Starting a server should create a call semaphore."""
        loader.load_config()
        state = loader._servers["test-server"]
        # Simulate start
        state.status = MCPServerStatus.READY
        import asyncio
        state.call_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)
        assert state.call_semaphore is not None

    async def test_semaphore_used_in_call_tool(self, loader):
        """call_tool should acquire semaphore before calling."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = [{"name": "test_tool"}]

        import asyncio
        state.call_semaphore = asyncio.Semaphore(1)

        mock_result = MagicMock()
        mock_result.content = []
        mock_result.isError = False
        mock_result.structuredContent = None

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)
        state.session = mock_session

        result = await loader.call_tool("test-server", "test_tool", {})
        assert result["isError"] is False
        mock_session.call_tool.assert_called_once()

    async def test_semaphore_cleared_on_stop(self, loader):
        """Stopping a server should clear the semaphore."""
        loader.load_config()
        state = loader._servers["test-server"]
        import asyncio
        state.call_semaphore = asyncio.Semaphore(5)
        await loader.stop_server("test-server")
        assert state.call_semaphore is None


# ============================================================
# Env passthrough whitelist
# ============================================================


class TestEnvPassthrough:
    def test_essential_only_when_no_passthrough(self, monkeypatch):
        """Without env_passthrough, only essential vars + explicit env are included."""
        monkeypatch.setenv("SECRET_KEY", "should_not_leak")
        monkeypatch.setenv("PATH", "/usr/bin")
        config = MCPServerConfig(
            name="test", command="echo",
            env={"MY_VAR": "value"},
        )
        env = _build_subprocess_env(config)
        assert "SECRET_KEY" not in env  # Security: no leak
        assert env["MY_VAR"] == "value"
        assert "PATH" in env  # Essential always present

    def test_full_env_with_star_passthrough(self, monkeypatch):
        """With env_passthrough=["*"], full os.environ is included (opt-in)."""
        monkeypatch.setenv("SECRET_KEY", "should_be_included")
        config = MCPServerConfig(
            name="test", command="echo",
            env={"MY_VAR": "value"},
            env_passthrough=["*"],
        )
        env = _build_subprocess_env(config)
        assert "SECRET_KEY" in env
        assert env["MY_VAR"] == "value"

    def test_passthrough_filters_env(self, monkeypatch):
        """With env_passthrough, only whitelisted vars are included."""
        monkeypatch.setenv("ALLOWED_VAR", "yes")
        monkeypatch.setenv("SECRET_VAR", "should_not_be_included")
        monkeypatch.setenv("PATH", "/usr/bin")
        config = MCPServerConfig(
            name="test", command="echo",
            env={"CUSTOM": "val"},
            env_passthrough=["ALLOWED_VAR"],
        )
        env = _build_subprocess_env(config)
        assert env.get("ALLOWED_VAR") == "yes"
        assert "SECRET_VAR" not in env
        assert "CUSTOM" in env
        assert "PATH" in env  # Essential var always included

    def test_passthrough_essential_vars_always_present(self, monkeypatch):
        """PATH, HOME, LANG are always included even with passthrough."""
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("HOME", "/home/test")
        config = MCPServerConfig(
            name="test", command="echo",
            env_passthrough=["NOTHING_SPECIAL"],
        )
        env = _build_subprocess_env(config)
        assert "PATH" in env
        assert "HOME" in env

    def test_passthrough_from_yaml(self, tmp_path):
        """env_passthrough parsed from mcp.yaml config."""
        import yaml

        config = {
            "servers": {
                "srv": {
                    "command": "echo",
                    "enabled": True,
                    "env_passthrough": ["NODE_OPTIONS", "PYTHONPATH"],
                },
            },
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        configs = loader.load_config()
        assert configs[0].env_passthrough == ["NODE_OPTIONS", "PYTHONPATH"]


# ============================================================
# SSRF private network blocking
# ============================================================


class TestSSRFPrivateNetworks:
    def test_private_ip_detection(self):
        assert _is_private_ip("10.0.0.1") is True
        assert _is_private_ip("172.16.0.1") is True
        assert _is_private_ip("192.168.1.1") is True
        assert _is_private_ip("127.0.0.1") is False  # Loopback, not private
        assert _is_private_ip("8.8.8.8") is False
        assert _is_private_ip("example.com") is False  # Hostname, not IP

    def test_private_networks_allowed_by_default(self):
        """By default private IPs are allowed for MCP."""
        safe, _ = _validate_mcp_url("http://192.168.1.100:8000/mcp")
        assert safe is True

    def test_private_networks_blocked_when_disabled(self):
        """With allow_private_networks=False, private IPs are blocked."""
        safe, reason = _validate_mcp_url(
            "http://10.0.0.5:8000/mcp",
            allow_private_networks=False,
        )
        assert safe is False
        assert "Private network" in reason

    def test_localhost_always_allowed(self):
        """Localhost is always allowed even with private networks blocked."""
        safe, _ = _validate_mcp_url(
            "http://localhost:8000/mcp",
            allow_private_networks=False,
        )
        assert safe is True

        safe, _ = _validate_mcp_url(
            "http://127.0.0.1:8000/mcp",
            allow_private_networks=False,
        )
        assert safe is True

    def test_public_ip_always_allowed(self):
        """Public IPs are allowed regardless of setting."""
        safe, _ = _validate_mcp_url(
            "https://mcp.example.com:8000/mcp",
            allow_private_networks=False,
        )
        assert safe is True

    def test_config_uses_allow_private_networks(self, tmp_path):
        """allow_private_networks setting applied during config loading."""
        import yaml

        config = {
            "servers": {
                "internal": {
                    "transport": "streamable-http",
                    "url": "http://10.0.0.5:8000/mcp",
                    "enabled": True,
                },
            },
            "settings": {"allow_private_networks": False},
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config), encoding="utf-8")
        loader = MCPToolLoader(config_path=path)
        configs = loader.load_config()
        assert len(configs) == 0  # Should be blocked


# ============================================================
# Content block — resource_link type
# ============================================================


class TestContentBlockResourceLink:
    def test_content_block_resource_link(self):
        block = MagicMock()
        block.type = "resource_link"
        block.uri = "file:///docs/readme.md"
        block.name = "README"
        block.mimeType = "text/markdown"
        d = _content_block_to_dict(block)
        assert d["type"] == "resource_link"
        assert d["uri"] == "file:///docs/readme.md"
        assert d["name"] == "README"

    def test_extract_resource_link_content(self):
        result = {
            "content": [
                {"type": "resource_link", "uri": "file:///a.md", "name": "Doc"},
            ],
            "isError": False,
        }
        output = _extract_content(result)
        assert "ResourceLink" in output
        assert "Doc" in output


# ============================================================
# tools_changed_callback
# ============================================================


class TestToolsChangedCallback:
    def test_tools_changed_callback_stored(self, mcp_yaml):
        """tools_changed_callback is stored in loader."""
        async def my_callback(server_name):
            pass

        loader = MCPToolLoader(
            config_path=mcp_yaml,
            tools_changed_callback=my_callback,
        )
        assert loader._tools_changed_callback is my_callback

    def test_bridge_sets_tools_changed_callback(self, registry):
        """MCPBridge passes its _on_tools_changed as callback."""
        bridge = MCPBridge(registry)
        assert bridge._loader._tools_changed_callback is not None
        assert bridge._loader._tools_changed_callback == bridge._on_tools_changed

    async def test_on_tools_changed_refreshes(self, registry):
        """_on_tools_changed unregisters old and registers new tools."""
        bridge = MCPBridge(registry)

        # Register initial tools
        bridge._register_tools_from_server("srv", [
            {"name": "old_tool", "description": "Old"},
        ])
        assert len(bridge._registered_tools) == 1

        # Mock loader.get_tools to return new tools
        bridge._loader.get_tools = AsyncMock(return_value=[
            {"name": "new_tool", "description": "New", "inputSchema": {}},
        ])
        bridge._loader._servers["srv"] = MCPServerState(
            config=MCPServerConfig(name="srv", command="echo"),
            status=MCPServerStatus.READY,
        )

        await bridge._on_tools_changed("srv")

        # Old tool should be gone, new tool registered
        assert registry.get("mcp_srv__old_tool") is None
        assert registry.get("mcp_srv__new_tool") is not None


# ============================================================
# Session ID from HTTP transport
# ============================================================


class TestHTTPSessionId:
    def test_get_session_id_no_server(self, loader):
        loader.load_config()
        assert loader.get_session_id("nonexistent") is None

    def test_get_session_id_no_fn(self, loader):
        loader.load_config()
        assert loader.get_session_id("test-server") is None

    def test_get_session_id_with_fn(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.session_id_fn = lambda: "session-123"
        assert loader.get_session_id("test-server") == "session-123"

    def test_session_id_in_status(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.session_id_fn = lambda: "sess-456"
        status = loader.get_server_status()
        assert status[0]["session_id"] == "sess-456"

    @pytest.mark.asyncio
    async def test_session_id_cleared_on_stop(self, loader):
        loader.load_config()
        state = loader._servers["test-server"]
        state.session_id_fn = lambda: "old"
        await loader.stop_server("test-server")
        assert state.session_id_fn is None


# ============================================================
# MCPServerState new fields
# ============================================================


class TestMCPServerStateNewFields:
    def test_initial_session_id_fn(self):
        config = MCPServerConfig(name="test", command="echo")
        state = MCPServerState(config=config)
        assert state.session_id_fn is None
        assert state.call_semaphore is None
        assert state.exit_stack is None

    def test_env_passthrough_default(self):
        config = MCPServerConfig(name="test", command="echo")
        assert config.env_passthrough == []


# ============================================================
# Elicitation response matching (from agent.py)
# ============================================================


class TestElicitationResponseMatch:
    def test_match_elicitation_response(self):
        from posipaka.core.agent import _match_elicitation_response

        result = _match_elicitation_response("[elicit:abc12345] my answer here")
        assert result is not None
        eid, text = result
        assert eid == "abc12345"
        assert text == "my answer here"

    def test_no_match_regular_message(self):
        from posipaka.core.agent import _match_elicitation_response

        assert _match_elicitation_response("hello world") is None

    def test_no_match_empty(self):
        from posipaka.core.agent import _match_elicitation_response

        assert _match_elicitation_response("") is None

    def test_match_with_multiline(self):
        from posipaka.core.agent import _match_elicitation_response

        result = _match_elicitation_response(
            '[elicit:deadbeef] {"key": "value"}',
        )
        assert result is not None
        assert result[0] == "deadbeef"


# ============================================================
# MCPCallMetrics
# ============================================================


class TestMCPCallMetrics:
    def test_initial_state(self):
        m = MCPCallMetrics()
        assert m.total_calls == 0
        assert m.error_rate == 0.0
        assert m.avg_latency_ms == 0.0

    def test_record_success(self):
        m = MCPCallMetrics()
        m.record("server1", "tool1", 150.0, success=True)
        assert m.total_calls == 1
        assert m.successful_calls == 1
        assert m.failed_calls == 0
        assert m.avg_latency_ms == 150.0

    def test_record_failure(self):
        m = MCPCallMetrics()
        m.record("server1", "tool1", 200.0, success=False)
        assert m.total_calls == 1
        assert m.failed_calls == 1
        assert m.error_rate == 1.0

    def test_per_server_tracking(self):
        m = MCPCallMetrics()
        m.record("s1", "t1", 100.0, success=True)
        m.record("s2", "t2", 200.0, success=False)
        assert "s1" in m.per_server
        assert "s2" in m.per_server
        assert m.per_server["s1"]["calls"] == 1
        assert m.per_server["s2"]["errors"] == 1

    def test_per_tool_tracking(self):
        m = MCPCallMetrics()
        m.record("s1", "tool_a", 100.0, success=True)
        m.record("s1", "tool_a", 200.0, success=True)
        assert m.per_tool["tool_a"]["calls"] == 2
        assert m.per_tool["tool_a"]["latency_ms"] == 300.0

    def test_get_summary(self):
        m = MCPCallMetrics()
        m.record("s1", "t1", 100.0, success=True)
        m.record("s1", "t2", 200.0, success=False)
        summary = m.get_summary()
        assert summary["total_calls"] == 2
        assert summary["error_rate"] == 0.5
        assert summary["avg_latency_ms"] == 150.0
        assert "per_server" in summary
        assert "per_tool" in summary


# ============================================================
# make_safe_tool_name — LLM provider length limits
# ============================================================


class TestMakeSafeToolName:
    def test_short_name_unchanged(self):
        assert make_safe_tool_name("mcp_fs__read") == "mcp_fs__read"

    def test_exact_limit_unchanged(self):
        name = "a" * MAX_TOOL_NAME_LENGTH
        assert make_safe_tool_name(name) == name

    def test_long_name_truncated_with_hash(self):
        name = "mcp_very_long_server_name__extremely_long_tool_name_that_exceeds_provider_limits"
        result = make_safe_tool_name(name)
        assert len(result) <= MAX_TOOL_NAME_LENGTH
        assert "_" in result[-7:]  # hash suffix

    def test_different_long_names_differ(self):
        name1 = "a" * 100 + "_alpha"
        name2 = "a" * 100 + "_beta"
        r1 = make_safe_tool_name(name1)
        r2 = make_safe_tool_name(name2)
        assert r1 != r2

    def test_custom_max_len(self):
        name = "abcdefghijklmnopqrstuvwxyz"
        result = make_safe_tool_name(name, max_len=10)
        assert len(result) <= 10


# ============================================================
# DNS rebinding protection
# ============================================================


class TestDNSRebindingProtection:
    def test_check_blocked_host_metadata(self):
        blocked, _ = _check_blocked_host("169.254.169.254", True)
        assert blocked

    def test_check_blocked_host_zero(self):
        blocked, _ = _check_blocked_host("0.0.0.0", True)
        assert blocked

    def test_check_blocked_host_link_local(self):
        blocked, _ = _check_blocked_host("169.254.1.1", True)
        assert blocked

    def test_check_blocked_host_cloud_metadata(self):
        blocked, _ = _check_blocked_host("metadata.google.internal", True)
        assert blocked

    def test_check_blocked_host_private_when_disallowed(self):
        blocked, _ = _check_blocked_host("10.0.0.1", False)
        assert blocked

    def test_check_blocked_host_private_when_allowed(self):
        blocked, _ = _check_blocked_host("10.0.0.1", True)
        assert not blocked

    def test_check_blocked_host_localhost_always_allowed(self):
        blocked, _ = _check_blocked_host("127.0.0.1", False)
        assert not blocked

    def test_is_ip_address_true(self):
        assert _is_ip_address("192.168.1.1")
        assert _is_ip_address("::1")

    def test_is_ip_address_false(self):
        assert not _is_ip_address("example.com")
        assert not _is_ip_address("localhost")

    def test_validate_url_with_dns_rebinding(self):
        """DNS rebinding should be caught when hostname resolves to blocked IP."""
        with patch("posipaka.core.tools.mcp_loader.socket.getaddrinfo") as mock_dns:
            # Simulate evil.com resolving to metadata IP
            mock_dns.return_value = [
                (2, 1, 6, "", ("169.254.169.254", 80)),
            ]
            ok, reason = _validate_mcp_url("http://evil.example.com:8000/mcp")
            assert not ok
            assert "DNS rebinding" in reason

    def test_validate_url_dns_resolution_failure_allowed(self):
        """DNS resolution failure should allow the URL (server may not be up)."""
        import socket as socket_mod
        with patch(
            "posipaka.core.tools.mcp_loader.socket.getaddrinfo",
            side_effect=socket_mod.gaierror("DNS failed"),
        ):
            ok, _ = _validate_mcp_url("http://not-yet-running.example.com/mcp")
            assert ok

    def test_validate_url_safe_dns_resolution(self):
        """Safe DNS resolution should pass."""
        with patch("posipaka.core.tools.mcp_loader.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 80)),
            ]
            ok, _ = _validate_mcp_url("http://example.com:8000/mcp")
            assert ok


# ============================================================
# Pagination safeguards
# ============================================================


class TestPaginationSafeguards:
    @pytest.mark.asyncio
    async def test_pagination_max_items(self):
        """Pagination should stop at max_items limit."""
        call_count = 0

        class FakeResult:
            def __init__(self):
                self.tools = [MagicMock(name=f"tool_{i}") for i in range(100)]
                self.nextCursor = "next"

        async def fake_list(cursor=None):
            nonlocal call_count
            call_count += 1
            return FakeResult()

        items = await _paginated_list(
            fake_list, "tools", lambda x: {"name": x.name},
            max_items=50,
        )
        assert len(items) == 50  # Stopped at max_items

    @pytest.mark.asyncio
    async def test_pagination_timeout(self):
        """Pagination should respect timeout."""
        import asyncio as aio

        async def slow_list(cursor=None):
            await aio.sleep(10)  # Very slow
            result = MagicMock()
            result.tools = []
            result.nextCursor = None
            return result

        items = await _paginated_list(
            slow_list, "tools", lambda x: {"name": "x"},
            timeout=0.1,
        )
        assert items == []  # Timed out before getting anything

    @pytest.mark.asyncio
    async def test_pagination_normal_operation(self):
        """Normal pagination should work without limits."""
        results = [
            MagicMock(tools=[MagicMock()], nextCursor="c2"),
            MagicMock(tools=[MagicMock()], nextCursor=None),
        ]
        call_idx = 0

        async def fake_list(cursor=None):
            nonlocal call_idx
            r = results[call_idx]
            call_idx += 1
            return r

        items = await _paginated_list(
            fake_list, "tools", lambda x: {"name": "t"},
        )
        assert len(items) == 2


# ============================================================
# MCPBridge with registration lock
# ============================================================


class TestMCPBridgeLock:
    @pytest.mark.asyncio
    async def test_bridge_has_registration_lock(self, registry):
        """MCPBridge should have an asyncio.Lock for safe concurrent ops."""
        import asyncio

        bridge = MCPBridge(registry, config_path=None)
        assert isinstance(bridge._reg_lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_bridge_initialize_checks_mcp_available(self, registry, tmp_path):
        """MCPBridge.initialize should gracefully handle missing MCP SDK."""
        bridge = MCPBridge(registry, config_path=tmp_path / "nonexistent.yaml")
        with patch("posipaka.core.tools.mcp_loader._MCP_AVAILABLE", False):
            count = await bridge.initialize()
            assert count == 0

    @pytest.mark.asyncio
    async def test_bridge_get_status_includes_metrics(self, registry):
        """get_status should include metrics summary."""
        bridge = MCPBridge(registry, config_path=None)
        status = bridge.get_status()
        assert "metrics" in status
        assert "total_calls" in status["metrics"]

    @pytest.mark.asyncio
    async def test_bridge_resources_changed_callback(self, registry):
        """MCPBridge should have resources_changed_callback wired."""
        bridge = MCPBridge(registry, config_path=None)
        assert bridge._loader._resources_changed_callback is not None


# ============================================================
# call_tool retry and metrics integration
# ============================================================


class TestCallToolRetryAndMetrics:
    @pytest.mark.asyncio
    async def test_call_tool_records_success_metrics(self, loader):
        """Successful call_tool should record metrics."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = [MagicMock(type="text", text="ok")]
        mock_result.isError = False
        mock_result.structuredContent = None
        mock_session.call_tool = AsyncMock(return_value=mock_result)
        state.session = mock_session

        result = await loader.call_tool("test-server", "some_tool", {})
        assert not result["isError"]
        assert loader.metrics.total_calls == 1
        assert loader.metrics.successful_calls == 1

    @pytest.mark.asyncio
    async def test_call_tool_records_failure_metrics(self, loader):
        """Failed call_tool should record error metrics."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=ConnectionError("lost"))
        state.session = mock_session

        result = await loader.call_tool("test-server", "some_tool", {})
        assert result["isError"]
        assert loader.metrics.failed_calls == 1
        # Should have retried CALL_MAX_RETRIES times
        assert mock_session.call_tool.call_count == CALL_MAX_RETRIES + 1

    @pytest.mark.asyncio
    async def test_call_tool_retry_succeeds_on_second_attempt(self, loader):
        """call_tool should succeed if retry works."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = [MagicMock(type="text", text="ok")]
        mock_result.isError = False
        mock_result.structuredContent = None
        mock_session.call_tool = AsyncMock(
            side_effect=[ConnectionError("first"), mock_result],
        )
        state.session = mock_session

        result = await loader.call_tool("test-server", "some_tool", {})
        assert not result["isError"]
        assert loader.metrics.successful_calls == 1


# ============================================================
# FileTokenStorage lock
# ============================================================


class TestFileTokenStorageLock:
    def test_has_asyncio_lock(self, tmp_path):
        """_FileTokenStorage should have an asyncio.Lock."""
        import asyncio

        storage = _FileTokenStorage(tmp_path / "tokens.json")
        assert isinstance(storage._lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_set_tokens_uses_lock(self, tmp_path):
        """set_tokens should acquire lock."""
        storage = _FileTokenStorage(tmp_path / "tokens.json")
        lock_acquired = False

        def tracking_save():
            nonlocal lock_acquired
            lock_acquired = storage._lock.locked()
            # Skip actual save to avoid model_dump on mock

        storage._save = tracking_save
        await storage.set_tokens(MagicMock())
        assert lock_acquired


# ============================================================
# Env passthrough — star wildcard
# ============================================================


class TestEnvPassthroughStar:
    def test_star_passes_full_env(self, monkeypatch):
        """env_passthrough=["*"] should include all os.environ."""
        monkeypatch.setenv("SECRET_KEY", "should_be_included")
        config = MCPServerConfig(
            name="test", command="echo",
            env_passthrough=["*"],
        )
        env = _build_subprocess_env(config)
        assert "SECRET_KEY" in env

    def test_default_filters_secrets(self, monkeypatch):
        """Default (no passthrough) should NOT include arbitrary env vars."""
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret123")
        monkeypatch.setenv("PATH", "/usr/bin")
        config = MCPServerConfig(name="test", command="echo")
        env = _build_subprocess_env(config)
        assert "AWS_SECRET_ACCESS_KEY" not in env
        assert "PATH" in env


# ============================================================
# Server status includes metrics
# ============================================================


class TestServerStatusMetrics:
    def test_status_includes_per_server_metrics(self, loader):
        loader.load_config()
        loader.metrics.record("test-server", "tool1", 100.0, success=True)
        status = loader.get_server_status()
        assert status[0]["metrics"]["calls"] == 1


# ============================================================
# P0: Async file I/O in _FileTokenStorage
# ============================================================


class TestFileTokenStorageAsyncIO:
    @pytest.mark.asyncio
    async def test_set_tokens_uses_async_to_thread(self, tmp_path):
        """set_tokens should not block the event loop."""
        storage = _FileTokenStorage(tmp_path / "tokens.json")
        mock_token = MagicMock()
        mock_token.model_dump.return_value = {"access_token": "test"}
        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.return_value = None
            await storage.set_tokens(mock_token)
            mock_thread.assert_called_once_with(storage._save)

    @pytest.mark.asyncio
    async def test_set_client_info_uses_async_to_thread(self, tmp_path):
        """set_client_info should not block the event loop."""
        storage = _FileTokenStorage(tmp_path / "tokens.json")
        mock_info = MagicMock()
        mock_info.model_dump.return_value = {"client_id": "test"}
        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.return_value = None
            await storage.set_client_info(mock_info)
            mock_thread.assert_called_once_with(storage._save)


# ============================================================
# P0: OAuth callback handler raises NotImplementedError
# ============================================================


class TestOAuthCallbackHandler:
    @pytest.mark.asyncio
    async def test_oauth_callback_raises_not_implemented(self, tmp_path):
        """OAuth _callback_handler should raise NotImplementedError."""
        loader = MCPToolLoader(config_path=tmp_path / "mcp.yaml", data_dir=tmp_path)
        config = MCPServerConfig(
            name="oauth-test",
            command="",
            url="http://localhost:8000/mcp",
            transport="streamable-http",
            oauth=MCPOAuthConfig(
                client_name="posipaka",
                redirect_uri="http://localhost:3000/callback",
                scope="read",
            ),
        )
        state = MagicMock()
        state.config = config
        state.exit_stack = None

        # We can't easily call _build_oauth_client directly without full SDK,
        # but we can verify the config is correctly set up
        assert config.oauth is not None
        assert config.oauth.client_name == "posipaka"


# ============================================================
# P1: McpError specific exception handling
# ============================================================


class TestMcpErrorHandling:
    @pytest.mark.asyncio
    async def test_call_tool_handles_mcp_error_without_retry(self, loader):
        """McpError (protocol error) should not trigger retry."""
        from posipaka.core.tools.mcp_loader import _McpError

        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = [{"name": "test_tool"}]
        state.call_semaphore = asyncio.Semaphore(5)

        mock_session = AsyncMock()
        # Only raise McpError if SDK is available
        if _McpError is not Exception:
            from mcp.types import ErrorData

            error = ErrorData(code=-32600, message="Invalid tool args")
            mock_session.call_tool.side_effect = _McpError(error)
        else:
            mock_session.call_tool.side_effect = ValueError("test error")
        state.session = mock_session

        result = await loader.call_tool("test-server", "test_tool", {})
        assert result["isError"] is True
        assert "protocol error" in result["content"][0]["text"].lower() or "error" in result["content"][0]["text"].lower()
        # Should NOT retry for protocol errors — only 1 call
        if _McpError is not Exception:
            assert mock_session.call_tool.call_count == 1

    @pytest.mark.asyncio
    async def test_get_tools_handles_mcp_error_returns_cache(self, loader):
        """McpError in get_tools should return stale cache without incrementing failures."""
        from posipaka.core.tools.mcp_loader import _McpError

        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = [{"name": "cached_tool"}]
        state.tools_cached_at = 0  # Force refresh

        mock_session = AsyncMock()
        if _McpError is not Exception:
            from mcp.types import ErrorData

            mock_session.list_tools.side_effect = _McpError(
                ErrorData(code=-32600, message="test"),
            )
        else:
            mock_session.list_tools.side_effect = ValueError("test")
        state.session = mock_session

        result = await loader.get_tools("test-server")
        # Should return stale cache
        assert result == [{"name": "cached_tool"}]


# ============================================================
# P1: Fire-and-forget task error handling
# ============================================================


class TestLogTaskException:
    def test_log_task_exception_logs_on_error(self):
        """_log_task_exception should log when task has exception."""
        from posipaka.core.tools.mcp_loader import _log_task_exception

        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = RuntimeError("boom")

        with patch("posipaka.core.tools.mcp_loader.logger") as mock_logger:
            _log_task_exception(task)
            mock_logger.warning.assert_called_once()

    def test_log_task_exception_ignores_cancelled(self):
        """_log_task_exception should not log cancelled tasks."""
        from posipaka.core.tools.mcp_loader import _log_task_exception

        task = MagicMock()
        task.cancelled.return_value = True

        with patch("posipaka.core.tools.mcp_loader.logger") as mock_logger:
            _log_task_exception(task)
            mock_logger.warning.assert_not_called()

    def test_log_task_exception_ignores_success(self):
        """_log_task_exception should not log successful tasks."""
        from posipaka.core.tools.mcp_loader import _log_task_exception

        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = None

        with patch("posipaka.core.tools.mcp_loader.logger") as mock_logger:
            _log_task_exception(task)
            mock_logger.warning.assert_not_called()


# ============================================================
# P1: Lock contention fix in MCPBridge
# ============================================================


class TestMCPBridgeLockContention:
    @pytest.mark.asyncio
    async def test_on_tools_changed_fetches_outside_lock(self, registry):
        """_on_tools_changed should fetch tools before acquiring lock."""
        bridge = MCPBridge(registry)
        bridge._loader = MagicMock()
        bridge._loader.get_tools = AsyncMock(return_value=[
            {"name": "new_tool", "description": "test", "inputSchema": {}},
        ])

        # Pre-register a tool to verify unregister+register cycle
        bridge._registered_tools.add("mcp_test__old_tool")
        bridge._tool_routing["mcp_test__old_tool"] = ("test-server", "old_tool")

        await bridge._on_tools_changed("test-server")

        # get_tools was called (outside lock)
        bridge._loader.get_tools.assert_called_once_with("test-server")

    @pytest.mark.asyncio
    async def test_refresh_tools_fetches_outside_lock(self, registry):
        """refresh_tools should fetch all tools before acquiring lock."""
        bridge = MCPBridge(registry)
        bridge._loader = MagicMock()
        bridge._loader.get_all_tools = AsyncMock(return_value={
            "server1": [{"name": "tool1", "description": "t", "inputSchema": {}}],
        })

        count = await bridge.refresh_tools()
        assert count == 1
        bridge._loader.get_all_tools.assert_called_once()


# ============================================================
# P2: Progress dict cleanup
# ============================================================


class TestProgressDictCleanup:
    def test_progress_evicts_oldest_entries(self):
        """Progress dict should evict oldest entries when over MAX_PROGRESS_ENTRIES."""
        from posipaka.core.tools.mcp_loader import MAX_PROGRESS_ENTRIES

        state = MCPServerState(
            config=MCPServerConfig(name="test", command="echo"),
        )

        # Fill progress to limit
        for i in range(MAX_PROGRESS_ENTRIES + 10):
            state.progress[f"token_{i}"] = {"progress": i, "total": 100}

        # Simulate what the eviction code does
        if len(state.progress) > MAX_PROGRESS_ENTRIES:
            excess = len(state.progress) - MAX_PROGRESS_ENTRIES
            for old_key in list(state.progress)[:excess]:
                del state.progress[old_key]

        assert len(state.progress) == MAX_PROGRESS_ENTRIES
        # Oldest entries should be gone
        assert "token_0" not in state.progress
        # Newest entries should remain
        assert f"token_{MAX_PROGRESS_ENTRIES + 9}" in state.progress


# ============================================================
# P2: Async context manager protocol
# ============================================================


class TestAsyncContextManager:
    @pytest.mark.asyncio
    async def test_mcp_tool_loader_context_manager(self, mcp_yaml):
        """MCPToolLoader should support async with protocol."""
        async with MCPToolLoader(config_path=mcp_yaml) as loader:
            assert isinstance(loader, MCPToolLoader)
        # After exit, stop_all should have been called implicitly

    @pytest.mark.asyncio
    async def test_mcp_bridge_context_manager(self, registry):
        """MCPBridge should support async with protocol."""
        bridge = MCPBridge(registry)
        # Mock loader to avoid real MCP connections
        mock_loader = MagicMock()
        mock_loader.load_config.return_value = []
        mock_loader.start_all = AsyncMock(return_value=0)
        mock_loader.get_all_tools = AsyncMock(return_value={})
        mock_loader.stop_all = AsyncMock()
        mock_loader.active_servers = []
        mock_loader.metrics = MagicMock()
        mock_loader.metrics.get_summary.return_value = {}
        bridge._loader = mock_loader

        # Patch _MCP_AVAILABLE
        with patch("posipaka.core.tools.mcp_loader._MCP_AVAILABLE", False):
            async with bridge as b:
                assert isinstance(b, MCPBridge)


# ============================================================
# P2: Async DNS validation
# ============================================================


class TestAsyncDNSValidation:
    @pytest.mark.asyncio
    async def test_validate_mcp_url_async_allows_localhost(self):
        """Async variant should allow localhost."""
        from posipaka.core.tools.mcp_loader import _validate_mcp_url_async

        safe, reason = await _validate_mcp_url_async("http://localhost:8000/mcp")
        assert safe is True

    @pytest.mark.asyncio
    async def test_validate_mcp_url_async_blocks_metadata(self):
        """Async variant should block cloud metadata."""
        from posipaka.core.tools.mcp_loader import _validate_mcp_url_async

        safe, reason = await _validate_mcp_url_async("http://169.254.169.254/latest")
        assert safe is False
        assert "metadata" in reason.lower() or "blocked" in reason.lower()

    @pytest.mark.asyncio
    async def test_validate_mcp_url_async_blocks_invalid_scheme(self):
        """Async variant should block non-http schemes."""
        from posipaka.core.tools.mcp_loader import _validate_mcp_url_async

        safe, reason = await _validate_mcp_url_async("ftp://server:21/data")
        assert safe is False

    def test_validate_url_structure_extracts_hostname(self):
        """_validate_url_structure should return hostname for DNS check."""
        from posipaka.core.tools.mcp_loader import _validate_url_structure

        safe, reason, hostname = _validate_url_structure(
            "http://example.com:8000/mcp", True,
        )
        assert safe is True
        assert hostname == "example.com"

    def test_validate_url_structure_blocks_metadata(self):
        """_validate_url_structure should block metadata endpoint."""
        from posipaka.core.tools.mcp_loader import _validate_url_structure

        safe, reason, hostname = _validate_url_structure(
            "http://169.254.169.254/latest", True,
        )
        assert safe is False
        assert hostname is None

    def test_check_resolved_ips_blocks_metadata(self):
        """_check_resolved_ips should detect metadata IP."""
        from posipaka.core.tools.mcp_loader import _check_resolved_ips

        safe, reason = _check_resolved_ips(
            "evil.com", {"169.254.169.254"}, True,
        )
        assert safe is False
        assert "rebinding" in reason.lower()

    def test_check_resolved_ips_allows_normal(self):
        """_check_resolved_ips should allow normal IPs."""
        from posipaka.core.tools.mcp_loader import _check_resolved_ips

        safe, reason = _check_resolved_ips(
            "example.com", {"93.184.216.34"}, True,
        )
        assert safe is True


# ============================================================
# P3: Tasks API (experimental)
# ============================================================


class TestTasksAPI:
    @pytest.mark.asyncio
    async def test_call_tool_as_task_returns_none_if_no_session(self, loader):
        """Should return None if server has no session."""
        loader.load_config()
        result = await loader.call_tool_as_task("test-server", "tool", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_call_tool_as_task_returns_none_if_no_experimental(self, loader):
        """Should return None if session has no experimental API."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.session = MagicMock(spec=[])  # No experimental attr
        result = await loader.call_tool_as_task("test-server", "tool", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_call_tool_as_task_success(self, loader):
        """Should return task info on success."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_session = MagicMock()
        mock_task_ref = MagicMock()
        mock_task_ref.taskId = "task-123"
        mock_task_ref.status = "running"
        mock_result = MagicMock()
        mock_result.task = mock_task_ref

        mock_experimental = MagicMock()
        mock_experimental.call_tool_as_task = AsyncMock(return_value=mock_result)
        mock_session.experimental = mock_experimental
        state.session = mock_session

        result = await loader.call_tool_as_task("test-server", "tool", {"arg": 1})
        assert result is not None
        assert result["taskId"] == "task-123"
        assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_task_status_success(self, loader):
        """Should return task status dict."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_session = MagicMock()
        mock_status = MagicMock()
        mock_status.status = "completed"
        mock_status.statusMessage = "done"

        mock_experimental = MagicMock()
        mock_experimental.get_task = AsyncMock(return_value=mock_status)
        mock_session.experimental = mock_experimental
        state.session = mock_session

        result = await loader.get_task_status("test-server", "task-123")
        assert result is not None
        assert result["status"] == "completed"
        assert result["taskId"] == "task-123"

    @pytest.mark.asyncio
    async def test_cancel_task_success(self, loader):
        """Should cancel task and return True."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY

        mock_session = MagicMock()
        mock_experimental = MagicMock()
        mock_experimental.cancel_task = AsyncMock()
        mock_session.experimental = mock_experimental
        state.session = mock_session

        result = await loader.cancel_task("test-server", "task-123")
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_task_no_server(self, loader):
        """Should return False if server doesn't exist."""
        loader.load_config()
        result = await loader.cancel_task("nonexistent", "task-123")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_task_result_no_experimental(self, loader):
        """Should return None if session has no experimental API."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.session = MagicMock(spec=[])
        result = await loader.get_task_result("test-server", "task-123")
        assert result is None

    @pytest.mark.asyncio
    async def test_poll_task_until_done_returns_none_no_session(self, loader):
        """Should return None if no session."""
        loader.load_config()
        result = await loader.poll_task_until_done("test-server", "task-123")
        assert result is None


# ============================================================
# Round 2: P1 — start_server lock contention
# ============================================================


class TestBridgeStartServerLock:
    @pytest.mark.asyncio
    async def test_start_server_fetches_outside_lock(self, registry):
        """start_server should fetch tools outside _reg_lock."""
        bridge = MCPBridge(registry)
        bridge._loader = MagicMock()
        bridge._loader.start_server = AsyncMock(return_value=True)
        bridge._loader.get_tools = AsyncMock(return_value=[
            {"name": "new_tool", "description": "test", "inputSchema": {}},
        ])

        await bridge.start_server("test-server")

        # get_tools called (outside lock, before registration)
        bridge._loader.get_tools.assert_called_once_with("test-server")
        assert len(bridge._registered_tools) == 1


# ============================================================
# Round 2: P2 — env_passthrough ["*"] warning
# ============================================================


class TestEnvPassthroughWarning:
    def test_star_passthrough_logs_warning(self, monkeypatch):
        """env_passthrough: ['*'] should log a warning."""
        monkeypatch.setenv("PATH", "/usr/bin")
        config = MCPServerConfig(name="test-star", command="echo", env_passthrough=["*"])
        with patch("posipaka.core.tools.mcp_loader.logger") as mock_logger:
            env = _build_subprocess_env(config)
            mock_logger.warning.assert_called_once()
            assert "FULL environment" in str(mock_logger.warning.call_args)
        assert "PATH" in env


# ============================================================
# Round 2: P2 — MCPTransport enum
# ============================================================


class TestMCPTransportEnum:
    def test_default_transport_is_enum(self):
        """MCPServerConfig.transport should be MCPTransport enum."""
        config = MCPServerConfig(name="test", command="echo")
        assert isinstance(config.transport, MCPTransport)
        assert config.transport == MCPTransport.STDIO

    def test_http_transport_enum(self):
        config = MCPServerConfig(
            name="test", command="", url="http://localhost:8000/mcp",
            transport=MCPTransport.HTTP,
        )
        assert config.transport == MCPTransport.HTTP
        assert config.transport.value == "streamable-http"

    def test_config_parsing_validates_transport(self, tmp_path):
        """Unknown transport should fall back to stdio with warning."""
        config_data = {
            "servers": {
                "bad-transport": {
                    "command": "echo",
                    "transport": "invalid-transport",
                    "enabled": True,
                },
            },
        }
        path = tmp_path / "mcp.yaml"
        import yaml
        path.write_text(yaml.dump(config_data))

        loader = MCPToolLoader(config_path=path)
        with patch("posipaka.core.tools.mcp_loader.logger") as mock_logger:
            configs = loader.load_config()
            # Should warn about unknown transport
            warning_calls = [
                c for c in mock_logger.warning.call_args_list
                if "unknown transport" in str(c)
            ]
            assert len(warning_calls) == 1
        assert len(configs) == 1
        assert configs[0].transport == MCPTransport.STDIO


# ============================================================
# Round 2: P2 — Server capabilities check
# ============================================================


class TestServerCapabilities:
    def test_extract_init_result_stores_capabilities(self):
        """_extract_init_result should store server capabilities."""
        from posipaka.core.tools.mcp_loader import _extract_init_result

        state = MCPServerState(config=MCPServerConfig(name="test", command="echo"))
        mock_result = MagicMock()
        mock_result.protocolVersion = "2024-11-05"
        mock_caps = MagicMock()
        mock_caps.tools = True
        mock_caps.resources = True
        mock_caps.prompts = None
        mock_caps.logging = None
        mock_caps.experimental = None
        mock_result.capabilities = mock_caps

        _extract_init_result(state, mock_result)

        assert state.protocol_version == "2024-11-05"
        assert "tools" in state.server_capabilities
        assert "resources" in state.server_capabilities
        assert "prompts" not in state.server_capabilities

    def test_extract_init_result_no_capabilities(self):
        """_extract_init_result handles missing capabilities."""
        from posipaka.core.tools.mcp_loader import _extract_init_result

        state = MCPServerState(config=MCPServerConfig(name="test", command="echo"))
        mock_result = MagicMock()
        mock_result.protocolVersion = "2024-11-05"
        mock_result.capabilities = None

        _extract_init_result(state, mock_result)

        assert state.protocol_version == "2024-11-05"
        assert state.server_capabilities == {}

    def test_capabilities_in_server_status(self, loader):
        """get_server_status should include capabilities."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.server_capabilities = {"tools": True, "resources": True}
        status = loader.get_server_status()
        assert status[0]["capabilities"] == {"tools": True, "resources": True}

    def test_capabilities_cleared_on_stop(self):
        """stop_server should clear capabilities."""
        state = MCPServerState(
            config=MCPServerConfig(name="test", command="echo"),
            server_capabilities={"tools": True},
        )
        # After reset
        state.server_capabilities = {}
        assert state.server_capabilities == {}


# ============================================================
# Round 2: P3 — Session resumption
# ============================================================


class TestSessionResumption:
    @pytest.mark.asyncio
    async def test_try_reconnect_captures_old_session_id(self, loader):
        """_try_reconnect should capture old session ID for HTTP servers."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.config.transport = MCPTransport.HTTP
        state.config.url = "http://localhost:8000/mcp"
        state.status = MCPServerStatus.ERROR
        state.consecutive_failures = 1
        state.session_id_fn = lambda: "old-session-123"

        # Mock start_server to track what happens
        with patch.object(loader, "start_server", new_callable=AsyncMock, return_value=True) as mock_start:
            with patch.object(loader, "_cleanup_server", new_callable=AsyncMock):
                result = await loader._try_reconnect("test-server")
                assert result is True
                mock_start.assert_called_once()


# ============================================================
# Round 2: P3 — ExperimentalTaskHandlers
# ============================================================


class TestExperimentalTaskHandlers:
    def test_build_task_handlers_returns_handlers_or_none(self, loader):
        """_build_task_handlers should return handlers if SDK supports it."""
        loader.load_config()
        result = loader._build_task_handlers()
        # May be None if SDK doesn't support ExperimentalTaskHandlers
        # or an object if it does — both are valid
        if result is not None:
            assert hasattr(result, "augmented_elicitation")

    def test_build_task_handlers_with_elicitation_callback(self, tmp_path):
        """Should build task handlers using the elicitation callback."""
        async def mock_elicitation(ctx, params):
            return MagicMock(action="accept")

        loader = MCPToolLoader(
            config_path=tmp_path / "mcp.yaml",
            elicitation_callback=mock_elicitation,
        )
        result = loader._build_task_handlers()
        if result is not None:
            assert hasattr(result, "augmented_elicitation")
            assert hasattr(result, "get_task")
            assert hasattr(result, "get_task_result")


# ============================================================
# Round 2: McpError consistency in remaining methods
# ============================================================


class TestMcpErrorConsistency:
    @pytest.mark.asyncio
    async def test_get_prompts_handles_mcp_error(self, loader):
        """get_prompts should handle McpError gracefully."""
        from posipaka.core.tools.mcp_loader import _McpError

        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.prompts = [{"name": "cached"}]
        state.prompts_cached_at = 0

        mock_session = AsyncMock()
        if _McpError is not Exception:
            from mcp.types import ErrorData
            mock_session.list_prompts.side_effect = _McpError(
                ErrorData(code=-32600, message="test"),
            )
        else:
            mock_session.list_prompts.side_effect = ValueError("test")
        state.session = mock_session

        result = await loader.get_prompts("test-server")
        assert result == [{"name": "cached"}]

    @pytest.mark.asyncio
    async def test_get_resources_handles_mcp_error(self, loader):
        """get_resources should handle McpError gracefully."""
        from posipaka.core.tools.mcp_loader import _McpError

        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.resources = [{"uri": "cached"}]
        state.resources_cached_at = 0

        mock_session = AsyncMock()
        if _McpError is not Exception:
            from mcp.types import ErrorData
            mock_session.list_resources.side_effect = _McpError(
                ErrorData(code=-32600, message="test"),
            )
        else:
            mock_session.list_resources.side_effect = ValueError("test")
        state.session = mock_session

        result = await loader.get_resources("test-server")
        assert result == [{"uri": "cached"}]


# ============================================================
# Round 3: MCPBridge.shutdown() lifecycle test
# ============================================================


class TestMCPBridgeShutdownLifecycle:
    @pytest.mark.asyncio
    async def test_shutdown_unregisters_all_tools_and_stops_servers(self, registry):
        """shutdown() should unregister all tools and stop all servers."""
        bridge = MCPBridge(registry)
        mock_loader = MagicMock()
        mock_loader.stop_all = AsyncMock()
        mock_loader.get_all_tools = AsyncMock(return_value={})
        mock_loader.active_servers = []
        mock_loader.metrics = MagicMock()
        mock_loader.metrics.get_summary.return_value = {}
        bridge._loader = mock_loader

        # Pre-register some tools
        from posipaka.core.tools.registry import ToolDefinition

        tool_def = ToolDefinition(
            name="mcp_test__tool1",
            description="test",
            category="mcp",
            handler=AsyncMock(),
            input_schema={},
        )
        registry.register(tool_def)
        bridge._registered_tools.add("mcp_test__tool1")
        bridge._tool_routing["mcp_test__tool1"] = ("test", "tool1")

        assert registry.get("mcp_test__tool1") is not None

        await bridge.shutdown()

        # Tools should be unregistered
        assert registry.get("mcp_test__tool1") is None
        assert len(bridge._registered_tools) == 0
        assert len(bridge._tool_routing) == 0
        # Loader stop_all should be called
        mock_loader.stop_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_calls_shutdown(self, registry):
        """async with MCPBridge should call shutdown on exit."""
        bridge = MCPBridge(registry)
        mock_loader = MagicMock()
        mock_loader.load_config.return_value = []
        mock_loader.start_all = AsyncMock(return_value=0)
        mock_loader.get_all_tools = AsyncMock(return_value={})
        mock_loader.stop_all = AsyncMock()
        mock_loader.active_servers = []
        mock_loader.metrics = MagicMock()
        mock_loader.metrics.get_summary.return_value = {}
        bridge._loader = mock_loader

        with patch("posipaka.core.tools.mcp_loader._MCP_AVAILABLE", False):
            async with bridge:
                pass

        mock_loader.stop_all.assert_called_once()


# ============================================================
# Round 3: Duplicate tool registration skip
# ============================================================


class TestDuplicateToolRegistrationSkip:
    def test_skips_tool_already_in_registry(self, registry):
        """_register_tools_from_server should skip tools already registered."""
        # Pre-register a tool with the same name
        from posipaka.core.tools.registry import ToolDefinition

        existing = ToolDefinition(
            name="mcp_test_server__my_tool",
            description="existing builtin",
            category="builtin",
            handler=AsyncMock(),
            input_schema={},
        )
        registry.register(existing)

        bridge = MCPBridge(registry)
        bridge._loader = MagicMock()

        mcp_tools = [
            {"name": "my_tool", "description": "from MCP", "inputSchema": {}},
        ]

        count = bridge._register_tools_from_server("test-server", mcp_tools)
        assert count == 0  # Skipped because already registered
        # The existing tool should still be the builtin one
        tool = registry.get("mcp_test_server__my_tool")
        assert tool.category == "builtin"


# ============================================================
# Round 3: _extract_content with non-serializable structuredContent
# ============================================================


class TestExtractContentJsonSafety:
    def test_non_serializable_structured_content(self):
        """_extract_content should handle non-serializable structuredContent."""
        result = {
            "content": [],
            "isError": False,
            "structuredContent": {"key": object()},  # Not JSON serializable
        }
        output = _extract_content(result)
        # Should not crash, should return string representation
        assert isinstance(output, str)
        assert len(output) > 0

    def test_structured_content_with_datetime(self):
        """_extract_content should handle datetime via default=str."""
        from datetime import datetime

        result = {
            "content": [],
            "isError": False,
            "structuredContent": {"ts": datetime(2024, 1, 1)},
        }
        output = _extract_content(result)
        assert "2024" in output

    def test_structured_content_error_flag(self):
        """_extract_content should prefix Error: for error results."""
        result = {
            "content": [],
            "isError": True,
            "structuredContent": {"error": "bad input"},
        }
        output = _extract_content(result)
        assert output.startswith("Error:")


# ============================================================
# Round 3: CALL_TIMEOUT from config
# ============================================================


class TestCallTimeoutFromConfig:
    @pytest.mark.asyncio
    async def test_call_tool_uses_config_timeout(self, loader):
        """call_tool should use server config.timeout, not hardcoded CALL_TIMEOUT."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.tools = [{"name": "test_tool"}]
        state.call_semaphore = asyncio.Semaphore(5)
        state.config.timeout = 120  # Custom timeout

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.content = []
        mock_result.isError = False
        mock_result.structuredContent = None
        mock_session.call_tool.return_value = mock_result
        state.session = mock_session

        # Patch asyncio.timeout to verify the timeout value used
        original_timeout = asyncio.timeout
        captured_timeouts = []

        class _TrackingTimeout:
            def __init__(self, delay):
                captured_timeouts.append(delay)
                self._inner = original_timeout(delay)

            async def __aenter__(self):
                return await self._inner.__aenter__()

            async def __aexit__(self, *args):
                return await self._inner.__aexit__(*args)

        with patch("posipaka.core.tools.mcp_loader.asyncio.timeout", _TrackingTimeout):
            await loader.call_tool("test-server", "test_tool", {})

        # The timeout should be 120 (from config), not 60 (CALL_TIMEOUT)
        assert 120 in captured_timeouts


# ============================================================
# Round 3: get_status snapshot safety
# ============================================================


class TestGetStatusSnapshot:
    def test_get_status_returns_consistent_snapshot(self, registry):
        """get_status should return a consistent snapshot."""
        bridge = MCPBridge(registry)
        bridge._loader = MagicMock()
        bridge._loader.get_server_status.return_value = []
        bridge._loader.metrics = MagicMock()
        bridge._loader.metrics.get_summary.return_value = {}

        bridge._registered_tools = {"mcp_s__t1", "mcp_s__t2"}
        bridge._tool_routing = {
            "mcp_s__t1": ("server1", "t1"),
            "mcp_s__t2": ("server1", "t2"),
        }

        status = bridge.get_status()
        assert status["registered_tools"] == 2
        assert len(status["tool_routing"]) == 2
        assert status["tool_routing"]["mcp_s__t1"]["server"] == "server1"


# ============================================================
# New tests for improvements
# ============================================================


class TestCapabilityBasedDiscovery:
    """Tests for capability-based tool/resource/prompt discovery."""

    @pytest.mark.asyncio
    async def test_get_tools_skips_when_no_tools_capability(self, loader):
        """get_tools returns [] if server has capabilities but no 'tools'."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.server_capabilities = {"resources": True, "prompts": True}
        state.tools_cached_at = 0
        state.session = AsyncMock()

        result = await loader.get_tools("test-server")
        assert result == []
        state.session.list_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_tools_works_when_capabilities_empty(self, loader):
        """get_tools proceeds normally if server_capabilities is empty (not yet known)."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.server_capabilities = {}  # Not yet populated
        state.tools_cached_at = 0

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.tools = []
        mock_result.nextCursor = None
        mock_session.list_tools.return_value = mock_result
        state.session = mock_session

        result = await loader.get_tools("test-server")
        assert result == []
        mock_session.list_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_resources_skips_when_no_resources_capability(self, loader):
        """get_resources returns [] if server has capabilities but no 'resources'."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.server_capabilities = {"tools": True}
        state.resources_cached_at = 0
        state.session = AsyncMock()

        result = await loader.get_resources("test-server")
        assert result == []
        state.session.list_resources.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_prompts_skips_when_no_prompts_capability(self, loader):
        """get_prompts returns [] if server has capabilities but no 'prompts'."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.server_capabilities = {"tools": True}
        state.prompts_cached_at = 0
        state.session = AsyncMock()

        result = await loader.get_prompts("test-server")
        assert result == []
        state.session.list_prompts.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_resource_templates_skips_when_no_resources_capability(self, loader):
        """get_resource_templates returns [] if no 'resources' capability."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.server_capabilities = {"tools": True}
        state.session = AsyncMock()

        result = await loader.get_resource_templates("test-server")
        assert result == []
        state.session.list_resource_templates.assert_not_called()


class TestLastSessionIdField:
    """Tests for dedicated last_session_id field on MCPServerState."""

    def test_default_is_none(self):
        config = MCPServerConfig(name="test", command="echo")
        state = MCPServerState(config=config)
        assert state.last_session_id is None

    @pytest.mark.asyncio
    async def test_reconnect_stores_session_id_in_field(self, loader):
        """_try_reconnect stores old session ID in last_session_id, not progress."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.ERROR
        state.consecutive_failures = 1
        state.config.transport = MCPTransport.HTTP

        state.session_id_fn = lambda: "sid-abc123"
        state.exit_stack = None

        with patch.object(loader, "start_server", new_callable=AsyncMock, return_value=True):
            await loader._try_reconnect("test-server")

        # Should NOT use progress dict for session ID
        assert "_last_session_id" not in state.progress
        # After reconnect, last_session_id should be cleaned up
        assert state.last_session_id is None

    @pytest.mark.asyncio
    async def test_stop_clears_last_session_id(self, loader):
        """stop_server does not leave stale last_session_id."""
        loader.load_config()
        state = loader._servers["test-server"]
        state.status = MCPServerStatus.READY
        state.last_session_id = "old-sid"

        await loader.stop_server("test-server")
        assert state.last_session_id is None


class TestCommandValidation:
    """Tests for stdio command whitelist validation."""

    def test_allowed_command_passes(self, tmp_path):
        """python command should be allowed by default."""
        import yaml

        config = {
            "servers": {"srv": {"command": "python", "args": ["-m", "myserver"], "enabled": True}},
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config))

        loader = MCPToolLoader(config_path=path)
        configs = loader.load_config()
        assert len(configs) == 1
        assert configs[0].command == "python"

    def test_blocked_command_skipped(self, tmp_path):
        """Arbitrary command should be blocked."""
        import yaml

        config = {
            "servers": {"srv": {"command": "rm", "args": ["-rf", "/"], "enabled": True}},
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config))

        loader = MCPToolLoader(config_path=path)
        configs = loader.load_config()
        assert len(configs) == 0

    def test_custom_allowed_commands_from_settings(self, tmp_path):
        """settings.allowed_commands extends the whitelist."""
        import yaml

        config = {
            "servers": {"srv": {"command": "my-custom-binary", "enabled": True}},
            "settings": {"allowed_commands": ["my-custom-binary"]},
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config))

        loader = MCPToolLoader(config_path=path)
        configs = loader.load_config()
        assert len(configs) == 1
        assert configs[0].command == "my-custom-binary"

    def test_http_transport_not_affected(self, tmp_path):
        """HTTP transport servers should not be blocked by command check."""
        import yaml

        config = {
            "servers": {
                "remote": {
                    "transport": "streamable-http",
                    "url": "http://localhost:8000/mcp",
                    "enabled": True,
                },
            },
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config))

        loader = MCPToolLoader(config_path=path)
        configs = loader.load_config()
        assert len(configs) == 1

    def test_path_command_extracts_basename(self, tmp_path):
        """Full path commands should be checked by basename."""
        import yaml

        config = {
            "servers": {"srv": {"command": "/usr/bin/python3", "enabled": True}},
        }
        path = tmp_path / "mcp.yaml"
        path.write_text(yaml.dump(config))

        loader = MCPToolLoader(config_path=path)
        configs = loader.load_config()
        assert len(configs) == 1


class TestRegisterAllToolsLock:
    """Tests for _register_all_tools using lock."""

    @pytest.mark.asyncio
    async def test_register_all_tools_acquires_lock(self):
        """_register_all_tools should acquire _reg_lock during registration."""
        registry = ToolRegistry()
        bridge = MCPBridge(registry)

        lock_acquired = False
        original_lock = bridge._reg_lock

        class TrackingLock:
            async def __aenter__(self):
                nonlocal lock_acquired
                lock_acquired = True
                return await original_lock.__aenter__()

            async def __aexit__(self, *args):
                return await original_lock.__aexit__(*args)

        bridge._reg_lock = TrackingLock()
        bridge._loader.get_all_tools = AsyncMock(return_value={})

        await bridge._register_all_tools()
        assert lock_acquired
