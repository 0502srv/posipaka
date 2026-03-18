"""Тести для ToolRegistry."""

from __future__ import annotations

import pytest

from posipaka.core.tools.registry import (
    ToolDefinition,
    ToolDisabledError,
    ToolNotFoundError,
    ToolRegistry,
)


@pytest.fixture
def registry():
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            name="test_tool",
            description="A test tool",
            category="builtin",
            handler=lambda x: f"result: {x}",
            input_schema={
                "type": "object",
                "required": ["x"],
                "properties": {"x": {"type": "string"}},
            },
            tags=["test"],
        )
    )
    return reg


@pytest.mark.asyncio
async def test_register_and_execute(registry):
    result = await registry.execute("test_tool", {"x": "hello"})
    assert result == "result: hello"


@pytest.mark.asyncio
async def test_register_async_tool():
    reg = ToolRegistry()

    async def async_tool(msg: str) -> str:
        return f"async: {msg}"

    reg.register(
        ToolDefinition(
            name="async_tool",
            description="Async tool",
            category="builtin",
            handler=async_tool,
            input_schema={"type": "object", "properties": {"msg": {"type": "string"}}},
        )
    )
    result = await reg.execute("async_tool", {"msg": "test"})
    assert result == "async: test"


@pytest.mark.asyncio
async def test_unknown_tool_raises(registry):
    with pytest.raises(ToolNotFoundError):
        await registry.execute("nonexistent", {})


@pytest.mark.asyncio
async def test_disabled_tool_raises(registry):
    registry.disable("test_tool")
    with pytest.raises(ToolDisabledError):
        await registry.execute("test_tool", {"x": "hello"})


def test_schema_format_anthropic(registry):
    schemas = registry.get_schemas("anthropic")
    assert len(schemas) == 1
    assert schemas[0]["name"] == "test_tool"
    assert "input_schema" in schemas[0]


def test_schema_format_openai(registry):
    schemas = registry.get_schemas("openai")
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "test_tool"


def test_list_tools(registry):
    tools = registry.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "test_tool"


def test_enable_disable(registry):
    registry.disable("test_tool")
    tool = registry.get("test_tool")
    assert tool and not tool.enabled

    registry.enable("test_tool")
    tool = registry.get("test_tool")
    assert tool and tool.enabled


def test_decorator_registration():
    reg = ToolRegistry()

    @reg.tool(
        name="decorated_tool",
        description="A decorated tool",
        input_schema={"type": "object", "properties": {}},
    )
    def my_tool():
        return "ok"

    assert reg.get("decorated_tool") is not None


def test_skill_metadata(registry):
    metadata = registry.get_skill_metadata()
    assert "test_tool" in metadata
    assert "A test tool" in metadata
