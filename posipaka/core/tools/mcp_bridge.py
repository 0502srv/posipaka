"""MCPBridge — міст між MCP серверами та ToolRegistry."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

from posipaka.core.tools.mcp_loader import (
    MCPServerStatus,
    MCPToolLoader,
    make_safe_server_name,
    make_safe_tool_name,
)
from posipaka.core.tools.registry import ToolDefinition, ToolRegistry

__all__ = ["MCPBridge", "MCP_TOOL_PREFIX", "MCP_NAME_SEP", "MCP_CATEGORY"]

MCP_TOOL_PREFIX = "mcp_"
MCP_NAME_SEP = "__"
MCP_CATEGORY = "mcp"


class MCPBridge:
    def __init__(
        self,
        registry: ToolRegistry,
        config_path: Path | None = None,
        sampling_callback: Callable | None = None,
        elicitation_callback: Callable | None = None,
        progress_callback: Callable | None = None,
    ) -> None:
        self._registry = registry
        self._loader = MCPToolLoader(
            config_path,
            sampling_callback=sampling_callback,
            elicitation_callback=elicitation_callback,
            progress_callback=progress_callback,
            tools_changed_callback=self._on_tools_changed,
            resources_changed_callback=self._on_resources_changed,
        )
        self._registered_tools: set[str] = set()
        self._tool_routing: dict[str, tuple[str, str]] = {}
        self._reg_lock = asyncio.Lock()

    async def __aenter__(self) -> MCPBridge:
        await self.initialize()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.shutdown()

    async def _on_tools_changed(self, server_name: str) -> None:
        try:
            tools = await self._loader.get_tools(server_name)
            async with self._reg_lock:
                self._unregister_server_tools(server_name)
                self._register_tools_from_server(server_name, tools)
            logger.info(
                "MCP: auto-refreshed tools for '{}' in ToolRegistry",
                server_name,
            )
        except Exception as e:
            logger.warning(
                "MCP: failed to auto-refresh tools for '{}': {}",
                server_name,
                e,
            )

    async def _on_resources_changed(self, server_name: str) -> None:
        logger.info(
            "MCP: resources changed for '{}', cache invalidated",
            server_name,
        )

    @property
    def loader(self) -> MCPToolLoader:
        return self._loader

    async def initialize(self) -> int:
        """Завантажити конфіг, запустити сервери, зареєструвати tools."""
        from posipaka.core.tools.mcp_loader import _MCP_AVAILABLE

        if not _MCP_AVAILABLE:
            logger.warning("MCP SDK not installed, MCPBridge disabled")
            return 0

        configs = self._loader.load_config()
        if not configs:
            logger.debug("MCP: no servers configured")
            return 0

        started = await self._loader.start_all()
        logger.info("MCP: started {}/{} servers", started, len(configs))

        total_tools = await self._register_all_tools()
        logger.info("MCP: registered {} tools in ToolRegistry", total_tools)
        return total_tools

    async def refresh_tools(self) -> int:
        """Перезавантажити tools з усіх серверів."""
        all_tools = await self._loader.get_all_tools()
        async with self._reg_lock:
            self._unregister_all_tools()
            total = 0
            for server_name, tools in all_tools.items():
                total += self._register_tools_from_server(server_name, tools)
            return total

    async def start_server(self, name: str) -> bool:
        """Запустити конкретний сервер і зареєструвати його tools."""
        ok = await self._loader.start_server(name)
        if ok:
            tools = await self._loader.get_tools(name)
            async with self._reg_lock:
                self._register_tools_from_server(name, tools)
        return ok

    async def stop_server(self, name: str) -> None:
        """Зупинити сервер і видалити його tools з registry."""
        async with self._reg_lock:
            self._unregister_server_tools(name)
        await self._loader.stop_server(name)

    async def shutdown(self) -> None:
        """Зупинити всі сервери і прибрати tools."""
        async with self._reg_lock:
            self._unregister_all_tools()
        await self._loader.stop_all()

    async def _register_all_tools(self) -> int:
        """Зареєструвати tools з усіх активних серверів."""
        all_tools = await self._loader.get_all_tools()
        async with self._reg_lock:
            total = 0
            for server_name, tools in all_tools.items():
                count = self._register_tools_from_server(server_name, tools)
                total += count
            return total

    async def _register_server_tools(self, server_name: str) -> int:
        """Зареєструвати tools з одного сервера."""
        tools = await self._loader.get_tools(server_name)
        return self._register_tools_from_server(server_name, tools)

    def _register_tools_from_server(
        self,
        server_name: str,
        tools: list[dict],
    ) -> int:
        """Convert MCP tools → ToolDefinition and register."""
        count = 0
        for mcp_tool in tools:
            mcp_name = mcp_tool.get("name", "")
            if not mcp_name:
                continue

            registered_name = _make_tool_name(server_name, mcp_name)

            if self._registry.get(registered_name):
                logger.debug(
                    "MCP tool '{}' skipped (already registered)",
                    registered_name,
                )
                continue

            input_schema = mcp_tool.get("inputSchema", {})
            if not input_schema:
                logger.debug(
                    "MCP tool '{}' from '{}' has no inputSchema, using empty object",
                    mcp_name,
                    server_name,
                )
                input_schema = {"type": "object", "properties": {}}

            handler = self._make_handler(server_name, mcp_name)

            annotations = mcp_tool.get("annotations", {})
            needs_approval = annotations.get("destructiveHint", False)

            tags = ["mcp", f"mcp:{server_name}"]
            if annotations.get("readOnlyHint"):
                tags.append("readonly")
            if annotations.get("idempotentHint"):
                tags.append("idempotent")

            tool_def = ToolDefinition(
                name=registered_name,
                description=_build_description(server_name, mcp_tool),
                category=MCP_CATEGORY,
                handler=handler,
                input_schema=input_schema,
                tags=tags,
                requires_approval=needs_approval,
            )

            self._registry.register(tool_def)
            self._registered_tools.add(registered_name)
            self._tool_routing[registered_name] = (server_name, mcp_name)
            count += 1

        if count:
            logger.debug(
                "MCP: registered {} tools from server '{}'",
                count,
                server_name,
            )
        return count

    def _make_handler(
        self,
        server_name: str,
        mcp_name: str,
    ) -> Callable:
        """Створити async handler що маршрутизує виклик до MCP сервера."""
        loader = self._loader

        async def _handler(**kwargs: Any) -> str:
            try:
                result = await loader.call_tool(server_name, mcp_name, kwargs)
                return _extract_content(result)
            except Exception as e:
                logger.error(
                    "MCP tool handler error ({}/{}): {}",
                    server_name,
                    mcp_name,
                    e,
                )
                return f"Error calling MCP tool {mcp_name}: {e}"

        return _handler

    def _unregister_all_tools(self) -> None:
        """Видалити всі MCP tools з registry."""
        for name in self._registered_tools:
            self._registry.unregister(name)
        self._registered_tools.clear()
        self._tool_routing.clear()

    def _unregister_server_tools(self, server_name: str) -> None:
        to_remove = [name for name, (srv, _) in self._tool_routing.items() if srv == server_name]
        for name in to_remove:
            self._registry.unregister(name)
            self._registered_tools.discard(name)
            self._tool_routing.pop(name, None)

    def get_routing_info(self) -> dict[str, tuple[str, str]]:
        return dict(self._tool_routing)

    def get_status(self) -> dict:
        routing_snapshot = dict(self._tool_routing)
        tools_count = len(self._registered_tools)
        return {
            "servers": self._loader.get_server_status(),
            "registered_tools": tools_count,
            "tool_routing": {
                name: {"server": srv, "mcp_tool": tool}
                for name, (srv, tool) in routing_snapshot.items()
            },
            "metrics": self._loader.metrics.get_summary(),
        }

    async def health_check_and_recover(self) -> dict[str, bool]:
        results = await self._loader.health_check_all()
        failed = [name for name, ok in results.items() if not ok]
        if failed:
            reconnected = await self._loader.reconnect_failed_servers()
            if reconnected:
                logger.info(
                    "MCP: reconnected {} servers after health check",
                    reconnected,
                )
                # Fetch tools outside lock, then register under lock
                recovered_tools: dict[str, list[dict]] = {}
                for name in failed:
                    state = self._loader._servers.get(name)
                    if state and state.status == MCPServerStatus.READY:
                        recovered_tools[name] = await self._loader.get_tools(name)

                async with self._reg_lock:
                    for name, tools in recovered_tools.items():
                        self._unregister_server_tools(name)
                        self._register_tools_from_server(name, tools)

        return results


def _make_tool_name(server_name: str, mcp_name: str) -> str:
    clean_server = make_safe_server_name(server_name)
    clean_tool = mcp_name.replace("-", "_").replace(".", "_").replace(" ", "_")
    full_name = f"{MCP_TOOL_PREFIX}{clean_server}{MCP_NAME_SEP}{clean_tool}"
    return make_safe_tool_name(full_name)


def _build_description(server_name: str, mcp_tool: dict) -> str:
    desc = mcp_tool.get("description", "")
    if desc:
        return f"[MCP:{server_name}] {desc}"
    return f"[MCP:{server_name}] {mcp_tool.get('name', 'unknown tool')}"


def _extract_content(result: dict) -> str:
    content_list = result.get("content", [])
    is_error = result.get("isError", False)

    structured = result.get("structuredContent")
    if not content_list and structured is not None:
        try:
            output = json.dumps(structured, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            output = str(structured)
        if is_error:
            output = f"Error: {output}"
        return output

    texts: list[str] = []

    for item in content_list:
        item_type = item.get("type", "")
        if item_type == "text":
            texts.append(item.get("text", ""))
        elif item_type == "image":
            mime = item.get("mimeType", "image/*")
            texts.append(f"[Image: {mime}]")
        elif item_type == "resource":
            res = item.get("resource", {})
            text = res.get("text")
            if text:
                texts.append(text)
            else:
                texts.append(f"[Resource: {res.get('uri', 'unknown')}]")
        elif item_type == "audio":
            mime = item.get("mimeType", "audio/*")
            texts.append(f"[Audio: {mime}]")
        elif item_type == "resource_link":
            uri = item.get("uri", "unknown")
            name = item.get("name", "")
            label = name or uri
            texts.append(f"[ResourceLink: {label}]")
        elif item_type:
            logger.debug("MCP unknown content type: {}", item_type)
            texts.append(f"[{item_type}: {item.get('text', '...')}]")

    output = "\n".join(texts) if texts else str(result)
    if is_error:
        output = f"Error: {output}"
    return output
