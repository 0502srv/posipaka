"""MCPToolLoader — завантаження tools з MCP серверів."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import yaml
from loguru import logger


class MCPServerConfig:
    """Конфігурація одного MCP сервера."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        enabled: bool = True,
    ) -> None:
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.enabled = enabled


class MCPToolLoader:
    """
    Lazy loading MCP tools.

    Замість завантаження ВСІХ MCP tools в контекст,
    пріоритет: skills > integrations > mcp_servers.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or Path.home() / ".posipaka" / "mcp.yaml"
        self._servers: list[MCPServerConfig] = []
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._tool_cache: dict[str, list[dict]] = {}

    def load_config(self) -> list[MCPServerConfig]:
        """Завантажити mcp.yaml конфігурацію."""
        if not self._config_path.exists():
            return []

        try:
            data = yaml.safe_load(self._config_path.read_text(encoding="utf-8"))
            servers = data.get("servers", [])
            self._servers = [
                MCPServerConfig(
                    name=s["name"],
                    command=s["command"],
                    args=s.get("args", []),
                    env=self._resolve_env(s.get("env", {})),
                    enabled=s.get("enabled", True),
                )
                for s in servers
            ]
            logger.info(f"Loaded {len(self._servers)} MCP server configs")
            return self._servers
        except Exception as e:
            logger.error(f"Error loading mcp.yaml: {e}")
            return []

    async def start_server(self, server: MCPServerConfig) -> bool:
        """Запустити MCP сервер як subprocess."""
        if not server.enabled:
            return False

        try:
            env = {**os.environ, **server.env}
            cmd = [server.command, *server.args]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            self._processes[server.name] = process
            logger.info(f"MCP server started: {server.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to start MCP server {server.name}: {e}")
            return False

    async def stop_server(self, name: str) -> None:
        """Зупинити MCP сервер."""
        proc = self._processes.pop(name, None)
        if proc:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                proc.kill()
            logger.info(f"MCP server stopped: {name}")

    async def stop_all(self) -> None:
        for name in list(self._processes.keys()):
            await self.stop_server(name)

    async def get_tools(self, server_name: str) -> list[dict]:
        """Отримати список tools з MCP сервера."""
        if server_name in self._tool_cache:
            return self._tool_cache[server_name]

        proc = self._processes.get(server_name)
        if not proc or not proc.stdin or not proc.stdout:
            return []

        try:
            # Send tools/list request (MCP protocol)
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            }
            proc.stdin.write(
                (json.dumps(request) + "\n").encode()
            )
            await proc.stdin.drain()

            line = await asyncio.wait_for(
                proc.stdout.readline(), timeout=10
            )
            response = json.loads(line.decode())
            tools = response.get("result", {}).get("tools", [])
            self._tool_cache[server_name] = tools
            return tools
        except Exception as e:
            logger.error(f"MCP get_tools error ({server_name}): {e}")
            return []

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict
    ) -> str:
        """Викликати MCP tool."""
        proc = self._processes.get(server_name)
        if not proc or not proc.stdin or not proc.stdout:
            return f"MCP server '{server_name}' not running"

        try:
            request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            }
            proc.stdin.write(
                (json.dumps(request) + "\n").encode()
            )
            await proc.stdin.drain()

            line = await asyncio.wait_for(
                proc.stdout.readline(), timeout=30
            )
            response = json.loads(line.decode())

            if "error" in response:
                return f"MCP error: {response['error']}"

            result = response.get("result", {})
            content = result.get("content", [])
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return "\n".join(texts) or str(result)
        except TimeoutError:
            return f"MCP tool timeout: {tool_name}"
        except Exception as e:
            return f"MCP call error: {e}"

    async def search_tools(
        self, query: str, limit: int = 5
    ) -> list[dict]:
        """Знайти релевантні MCP tools за запитом (keyword match)."""
        query_lower = query.lower()
        all_tools = []

        for server in self._servers:
            if not server.enabled:
                continue
            tools = await self.get_tools(server.name)
            for tool in tools:
                score = 0.0
                name = tool.get("name", "").lower()
                desc = tool.get("description", "").lower()
                for word in query_lower.split():
                    if word in name:
                        score += 0.5
                    if word in desc:
                        score += 0.3
                if score > 0:
                    all_tools.append({**tool, "_score": score, "_server": server.name})

        all_tools.sort(key=lambda t: t["_score"], reverse=True)
        return all_tools[:limit]

    @staticmethod
    def _resolve_env(env: dict[str, str]) -> dict[str, str]:
        """Resolve ${VAR} references in env values."""
        resolved = {}
        for key, value in env.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                var_name = value[2:-1]
                resolved[key] = os.environ.get(var_name, "")
            else:
                resolved[key] = str(value)
        return resolved
