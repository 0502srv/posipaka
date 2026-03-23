"""MCPToolLoader — lifecycle MCP серверів через офіційний Python SDK."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import socket
import time as time_mod
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcp import ClientSession

import yaml
from loguru import logger

try:
    from mcp import ClientSession  # noqa: F811
    from mcp import McpError as _McpError
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.types import Implementation, Root

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    _McpError = Exception

CIRCUIT_BREAKER_THRESHOLD = 5
MAX_RESOURCE_SIZE = 10 * 1024 * 1024
MAX_CONCURRENT_CALLS = 5
MAX_TOOL_NAME_LENGTH = 64
MAX_PROGRESS_ENTRIES = 100
CALL_TIMEOUT = 60
CALL_MAX_RETRIES = 2
INIT_MAX_RETRIES = 2
TOOL_CACHE_TTL = 300
RESOURCE_CACHE_TTL = 300
PROMPT_CACHE_TTL = 300

_ESSENTIAL_VARS = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LANGUAGE",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "SHELL",
        "USER",
        "LOGNAME",
        "TMPDIR",
        "XDG_RUNTIME_DIR",
    }
)

_ALLOWED_COMMANDS = frozenset(
    {
        "node",
        "npx",
        "npm",
        "python",
        "python3",
        "uvx",
        "uv",
        "deno",
        "bun",
        "bunx",
        "docker",
        "podman",
    }
)

__all__ = [
    "MCPToolLoader",
    "MCPServerConfig",
    "MCPServerState",
    "MCPServerStatus",
    "MCPTransport",
    "MCPOAuthConfig",
    "MCPCallMetrics",
    "make_safe_server_name",
    "make_safe_tool_name",
]


class MCPTransport(StrEnum):
    STDIO = "stdio"
    HTTP = "streamable-http"


@dataclass
class MCPOAuthConfig:
    client_name: str = "posipaka"
    redirect_uri: str = "http://localhost:3000/callback"
    scope: str = ""


@dataclass
class MCPServerConfig:
    name: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    transport: MCPTransport = MCPTransport.STDIO
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    oauth: MCPOAuthConfig | None = None
    timeout: int = 30
    auto_start: bool = True
    roots: list[str] = field(default_factory=list)
    env_passthrough: list[str] = field(default_factory=list)


class MCPServerStatus(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    ERROR = "error"


@dataclass
class MCPServerState:
    config: MCPServerConfig
    status: MCPServerStatus = MCPServerStatus.STOPPED
    session: ClientSession | None = None
    exit_stack: AsyncExitStack | None = None
    tools: list[dict] = field(default_factory=list)
    tools_cached_at: float = 0.0
    resources: list[dict] = field(default_factory=list)
    resources_cached_at: float = 0.0
    resource_templates: list[dict] = field(default_factory=list)
    prompts: list[dict] = field(default_factory=list)
    prompts_cached_at: float = 0.0
    consecutive_failures: int = 0
    last_error: str = ""
    protocol_version: str = ""
    server_capabilities: dict = field(default_factory=dict)
    session_id_fn: Callable | None = None
    call_semaphore: asyncio.Semaphore | None = None
    progress: dict = field(default_factory=dict)
    last_session_id: str | None = None


class MCPCallMetrics:
    def __init__(self) -> None:
        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self._total_latency = 0.0
        self.per_server: dict[str, dict] = {}
        self.per_tool: dict[str, dict] = {}

    @property
    def error_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.failed_calls / self.total_calls

    @property
    def avg_latency_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self._total_latency / self.total_calls

    def record(
        self,
        server: str,
        tool: str,
        latency_ms: float,
        *,
        success: bool,
    ) -> None:
        self.total_calls += 1
        self._total_latency += latency_ms
        if success:
            self.successful_calls += 1
        else:
            self.failed_calls += 1

        srv = self.per_server.setdefault(server, {"calls": 0, "errors": 0, "latency_ms": 0.0})
        srv["calls"] += 1
        srv["latency_ms"] += latency_ms
        if not success:
            srv["errors"] += 1

        t = self.per_tool.setdefault(tool, {"calls": 0, "errors": 0, "latency_ms": 0.0})
        t["calls"] += 1
        t["latency_ms"] += latency_ms
        if not success:
            t["errors"] += 1

    def get_summary(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "error_rate": self.error_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "per_server": dict(self.per_server),
            "per_tool": dict(self.per_tool),
        }


try:
    from mcp.client.auth import TokenStorage as _TokenStorageBase
except ImportError:
    _TokenStorageBase = object  # type: ignore[assignment,misc]


class _FileTokenStorage(_TokenStorageBase):
    def __init__(self, path: Path) -> None:
        self._path = path
        self._tokens: Any = None
        self._client_info: Any = None
        self._lock = asyncio.Lock()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._tokens = data.get("tokens")
            self._client_info = data.get("client_info")
        except Exception as e:
            logger.debug("Failed to load token storage {}: {}", self._path, e)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if self._tokens is not None:
            try:
                data["tokens"] = self._tokens.model_dump()
            except AttributeError:
                data["tokens"] = self._tokens
        if self._client_info is not None:
            try:
                data["client_info"] = self._client_info.model_dump()
            except AttributeError:
                data["client_info"] = self._client_info
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.rename(self._path)

    async def get_tokens(self) -> Any:
        return self._tokens

    async def set_tokens(self, tokens: Any) -> None:
        async with self._lock:
            self._tokens = tokens
            await asyncio.to_thread(self._save)

    async def get_client_info(self) -> Any:
        return self._client_info

    async def set_client_info(self, info: Any) -> None:
        async with self._lock:
            self._client_info = info
            await asyncio.to_thread(self._save)


_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _env_replace(m: re.Match) -> str:
    var_expr = m.group(1)
    if ":-" in var_expr:
        var_name, default = var_expr.split(":-", 1)
        return os.environ.get(var_name, default)
    return os.environ.get(var_expr, "")


def _resolve_env(env: dict[str, Any]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, value in env.items():
        if not isinstance(value, str):
            resolved[key] = str(value)
        elif "${" in value:
            resolved[key] = _ENV_VAR_RE.sub(_env_replace, value)
        else:
            resolved[key] = value
    return resolved


def _build_subprocess_env(config: MCPServerConfig) -> dict[str, str]:
    env: dict[str, str] = {}

    if "*" in config.env_passthrough:
        logger.warning(
            "MCP server '{}': env_passthrough=['*'] — passing FULL environment",
            config.name,
        )
        env.update(os.environ)
    else:
        for var in _ESSENTIAL_VARS:
            val = os.environ.get(var)
            if val is not None:
                env[var] = val
        for var in config.env_passthrough:
            val = os.environ.get(var)
            if val is not None:
                env[var] = val

    env.update(config.env)
    return env


def _is_ip_address(host: str) -> bool:
    try:
        import ipaddress

        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _is_private_ip(host: str) -> bool:
    try:
        import ipaddress

        addr = ipaddress.ip_address(host)
        return addr.is_private and not addr.is_loopback
    except ValueError:
        return False


_BLOCKED_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
    }
)


def _check_blocked_host(
    host: str,
    allow_private: bool,
) -> tuple[bool, str]:
    if host in ("0.0.0.0",):
        return True, "Zero address blocked"

    if host.startswith("169.254."):
        return True, "Link-local address blocked"

    if host in _BLOCKED_HOSTS:
        return True, "Cloud metadata endpoint blocked"

    if _is_ip_address(host):
        import ipaddress

        addr = ipaddress.ip_address(host)
        if addr.is_loopback:
            return False, "ok"
        if addr.is_private and not allow_private:
            return True, f"Private network blocked: {host}"

    return False, "ok"


def _validate_url_structure(
    url: str,
    allow_private: bool,
) -> tuple[bool, str, str | None]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"Invalid scheme: {parsed.scheme}", None

    host = parsed.hostname or ""
    if not host:
        return False, "No hostname", None

    if host in ("localhost", "127.0.0.1", "::1"):
        return True, "ok", host

    blocked, reason = _check_blocked_host(host, allow_private)
    if blocked:
        return False, reason, None

    return True, "ok", host


def _check_resolved_ips(
    hostname: str,
    resolved_ips: set[str],
    allow_private: bool,
) -> tuple[bool, str]:
    for ip in resolved_ips:
        blocked, reason = _check_blocked_host(ip, allow_private)
        if blocked:
            return False, f"DNS rebinding: {hostname} -> {ip} ({reason})"
    return True, "ok"


def _validate_mcp_url(
    url: str,
    allow_private_networks: bool = True,
) -> tuple[bool, str]:
    safe, reason, hostname = _validate_url_structure(url, allow_private_networks)
    if not safe:
        return False, reason
    if hostname is None or hostname in ("localhost", "127.0.0.1", "::1"):
        return True, "ok"

    if not _is_ip_address(hostname):
        try:
            addrs = socket.getaddrinfo(hostname, None)
            resolved = {addr[4][0] for addr in addrs}
            safe, reason = _check_resolved_ips(hostname, resolved, allow_private_networks)
            if not safe:
                return False, reason
        except socket.gaierror:
            pass

    return True, "ok"


async def _validate_mcp_url_async(
    url: str,
    allow_private_networks: bool = True,
) -> tuple[bool, str]:
    return await asyncio.to_thread(_validate_mcp_url, url, allow_private_networks)


def make_safe_server_name(name: str, max_len: int = 20) -> str:
    clean = name.replace("-", "_").replace(".", "_").replace(" ", "_")
    while "__" in clean:
        clean = clean.replace("__", "_")
    if len(clean) <= max_len:
        return clean
    h = hashlib.sha256(name.encode()).hexdigest()[:6]
    return clean[: max_len - 7] + "_" + h


def make_safe_tool_name(name: str, max_len: int = MAX_TOOL_NAME_LENGTH) -> str:
    if len(name) <= max_len:
        return name
    h = hashlib.sha256(name.encode()).hexdigest()[:6]
    return name[: max_len - 7] + "_" + h


def _error_result(msg: str) -> dict:
    return {
        "isError": True,
        "content": [{"type": "text", "text": msg}],
    }


def _content_block_to_dict(block: Any) -> dict:
    btype = getattr(block, "type", "unknown")
    d: dict[str, Any] = {"type": btype}
    if btype == "text":
        d["text"] = getattr(block, "text", "")
    elif btype == "image":
        d["mimeType"] = getattr(block, "mimeType", "image/*")
        d["data"] = getattr(block, "data", "")
    elif btype == "audio":
        d["mimeType"] = getattr(block, "mimeType", "audio/*")
        d["data"] = getattr(block, "data", "")
    elif btype == "resource":
        res = getattr(block, "resource", None)
        if res:
            d["resource"] = {
                "uri": getattr(res, "uri", ""),
                "text": getattr(res, "text", None),
                "mimeType": getattr(res, "mimeType", None),
            }
    elif btype == "resource_link":
        d["uri"] = getattr(block, "uri", "")
        d["name"] = getattr(block, "name", "")
        d["mimeType"] = getattr(block, "mimeType", None)
    return d


def _resource_template_to_dict(tmpl: Any) -> dict:
    return {
        "uriTemplate": getattr(tmpl, "uriTemplate", ""),
        "name": getattr(tmpl, "name", ""),
        "description": getattr(tmpl, "description", ""),
        "mimeType": getattr(tmpl, "mimeType", None),
    }


def _prompt_content_to_str(content: Any) -> str:
    ctype = getattr(content, "type", "")
    if ctype == "text":
        return getattr(content, "text", "") or ""
    if ctype == "image":
        return f"[Image: {getattr(content, 'mimeType', 'image/*')}]"
    if ctype == "audio":
        return f"[Audio: {getattr(content, 'mimeType', 'audio/*')}]"
    if ctype == "resource":
        res = getattr(content, "resource", None)
        if res:
            text = getattr(res, "text", None)
            if text:
                return text
            return f"[Resource: {getattr(res, 'uri', 'unknown')}]"
    text = getattr(content, "text", None)
    if text:
        return text
    return str(content)


_MAX_PAGES = 100


async def _paginated_list(
    list_fn: Any,
    items_attr: str,
    convert_fn: Any,
    *,
    max_items: int = 10000,
    timeout: float = 30.0,
) -> list[dict]:
    items: list[dict] = []
    cursor: str | None = None
    try:
        async with asyncio.timeout(timeout):
            for _ in range(_MAX_PAGES):
                kwargs: dict[str, Any] = {}
                if cursor is not None:
                    kwargs["cursor"] = cursor
                result = await list_fn(**kwargs)
                raw_items = getattr(result, items_attr, [])
                for item in raw_items:
                    items.append(convert_fn(item))
                    if len(items) >= max_items:
                        return items
                cursor = getattr(result, "nextCursor", None)
                if not cursor:
                    break
    except TimeoutError:
        logger.warning("Paginated list timed out after {}s", timeout)
    return items


def _score_tool(words: list[str], query: str, tool: dict) -> float:
    name = tool.get("name", "").lower()
    desc = tool.get("description", "").lower()
    name_parts = re.split(r"[_\-.\s]+", name)
    score = 0.0

    for word in words:
        if len(word) < 2:
            continue
        best_word_score = 0.0
        if word in name:
            best_word_score = max(best_word_score, 0.6)
        if word in desc:
            best_word_score = max(best_word_score, 0.3)
        if best_word_score == 0:
            for part in name_parts:
                ratio = SequenceMatcher(None, word, part).ratio()
                if ratio >= 0.6:
                    best_word_score = max(best_word_score, ratio * 0.5)
        score += best_word_score

    return score


def _log_task_exception(task: Any) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("MCP background task failed: {}", exc)


def _extract_init_result(state: MCPServerState, result: Any) -> None:
    state.protocol_version = getattr(result, "protocolVersion", "")
    caps = getattr(result, "capabilities", None)
    if caps is None:
        state.server_capabilities = {}
        return
    cap_dict: dict[str, Any] = {}
    for attr in ("tools", "resources", "prompts", "logging", "experimental"):
        val = getattr(caps, attr, None)
        if val is not None:
            cap_dict[attr] = val
    state.server_capabilities = cap_dict


class MCPToolLoader:
    def __init__(
        self,
        config_path: Path | None = None,
        *,
        data_dir: Path | None = None,
        sampling_callback: Any = None,
        elicitation_callback: Any = None,
        progress_callback: Any = None,
        tools_changed_callback: Any = None,
        resources_changed_callback: Any = None,
    ) -> None:
        self._config_path = config_path or Path.home() / ".posipaka" / "mcp.yaml"
        self._data_dir = data_dir or Path.home() / ".posipaka"
        self._servers: dict[str, MCPServerState] = {}
        self._settings: dict[str, Any] = {}
        self._sampling_callback = sampling_callback
        self._elicitation_callback = elicitation_callback
        self._progress_callback = progress_callback
        self._tools_changed_callback = tools_changed_callback
        self._resources_changed_callback = resources_changed_callback
        self._inflight: dict[str, asyncio.Task] = {}
        self.metrics = MCPCallMetrics()

    async def __aenter__(self) -> MCPToolLoader:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop_all()

    @property
    def server_count(self) -> int:
        return len(self._servers)

    @property
    def active_servers(self) -> list[str]:
        return [name for name, s in self._servers.items() if s.status == MCPServerStatus.READY]

    def load_config(self) -> list[MCPServerConfig]:
        if not self._config_path.exists():
            return []

        try:
            raw = self._config_path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw)
        except Exception as e:
            logger.error("Error loading mcp.yaml: {}", e)
            return []

        if not data:
            return []

        self._settings = data.get("settings", {}) or {}
        max_servers = self._settings.get("max_servers", 50)
        timeout = self._settings.get("timeout_seconds", 30)
        allow_private = self._settings.get("allow_private_networks", True)

        raw_servers = data.get("servers", {})
        if raw_servers is None:
            return []

        server_list: list[tuple[str, dict]] = []
        if isinstance(raw_servers, dict):
            for name, cfg in raw_servers.items():
                if isinstance(cfg, dict):
                    server_list.append((name, cfg))
        elif isinstance(raw_servers, list):
            for cfg in raw_servers:
                if isinstance(cfg, dict) and "name" in cfg:
                    server_list.append((cfg["name"], cfg))

        configs: list[MCPServerConfig] = []
        for name, s in server_list:
            if len(configs) >= max_servers:
                break

            enabled = s.get("enabled", True)
            if not enabled:
                continue

            raw_transport = s.get("transport", "stdio")
            try:
                transport = MCPTransport(raw_transport)
            except ValueError:
                logger.warning(
                    "MCP server '{}': unknown transport '{}', falling back to stdio",
                    name,
                    raw_transport,
                )
                transport = MCPTransport.STDIO

            has_command = bool(s.get("command"))
            has_url = bool(s.get("url"))

            if transport == MCPTransport.HTTP and has_url:
                safe, reason = _validate_mcp_url(s["url"], allow_private)
                if not safe:
                    logger.warning(
                        "MCP server '{}': URL blocked ({}), skipping",
                        name,
                        reason,
                    )
                    continue

            oauth_data = s.get("oauth")
            oauth = None
            if oauth_data and isinstance(oauth_data, dict):
                oauth = MCPOAuthConfig(
                    client_name=oauth_data.get("client_name", "posipaka"),
                    redirect_uri=oauth_data.get("redirect_uri", "http://localhost:3000/callback"),
                    scope=oauth_data.get("scope", ""),
                )

            raw_headers = s.get("headers", {}) or {}
            headers = _resolve_env(raw_headers) if raw_headers else {}

            config = MCPServerConfig(
                name=name,
                command=s.get("command", ""),
                args=s.get("args", []) or [],
                env=_resolve_env(s.get("env", {}) or {}),
                enabled=True,
                transport=transport,
                url=s.get("url", ""),
                headers=headers,
                oauth=oauth,
                timeout=s.get("timeout", timeout),
                auto_start=s.get("auto_start", True),
                roots=s.get("roots", []) or [],
                env_passthrough=s.get("env_passthrough", []) or [],
            )

            if has_command and transport == MCPTransport.STDIO:
                extra = self._settings.get("allowed_commands", [])
                allowed = _ALLOWED_COMMANDS | frozenset(extra)
                base_cmd = Path(config.command).name
                if base_cmd not in allowed:
                    logger.warning(
                        "MCP server '{}': command '{}' not in allowed list, skipping",
                        name,
                        config.command,
                    )
                    continue

            if (has_command or has_url) and config.enabled:
                configs.append(config)
                state = MCPServerState(config=config)
                self._servers[name] = state

        logger.info("MCP: loaded {} server configs", len(configs))
        return configs

    async def start_all(self) -> int:
        if not _MCP_AVAILABLE:
            return 0

        auto_start = [
            name
            for name, s in self._servers.items()
            if s.config.auto_start and s.status == MCPServerStatus.STOPPED
        ]
        if not auto_start:
            return 0

        results = await asyncio.gather(
            *(self.start_server(name) for name in auto_start),
            return_exceptions=True,
        )
        return sum(1 for r in results if r is True)

    async def start_server(self, name: str) -> bool:
        if not _MCP_AVAILABLE:
            return False

        state = self._servers.get(name)
        if not state:
            return False

        if state.consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
            state.status = MCPServerStatus.ERROR
            logger.warning("MCP: circuit breaker open for '{}'", name)
            return False

        config = state.config
        state.status = MCPServerStatus.STARTING

        try:
            stack = AsyncExitStack()
            await stack.__aenter__()
            state.exit_stack = stack

            if config.transport == MCPTransport.STDIO:
                await self._start_stdio_server(state, stack)
            else:
                await self._start_http_server(state, stack)

            state.status = MCPServerStatus.READY
            state.consecutive_failures = 0
            state.call_semaphore = asyncio.Semaphore(
                self._settings.get("max_concurrent_calls", MAX_CONCURRENT_CALLS),
            )
            logger.info("MCP server started: {}", name)
            return True
        except Exception as e:
            state.status = MCPServerStatus.ERROR
            state.consecutive_failures += 1
            state.last_error = str(e)
            logger.error("Failed to start MCP server {}: {}", name, e)
            await self._cleanup_server(state)
            return False

    async def _start_stdio_server(
        self,
        state: MCPServerState,
        stack: AsyncExitStack,
    ) -> None:
        config = state.config
        env = _build_subprocess_env(config)

        params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=env,
        )

        read_stream, write_stream = await stack.enter_async_context(
            stdio_client(params),
        )

        kwargs = self._make_session_kwargs(state)
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream, **kwargs),
        )

        init_result = await self._initialize_with_retry(session, config)
        _extract_init_result(state, init_result)
        state.session = session

    async def _start_http_server(
        self,
        state: MCPServerState,
        stack: AsyncExitStack,
    ) -> None:
        config = state.config

        captured_session_ids: list[str] = []

        async def _on_response(response: Any) -> None:
            sid = response.headers.get("mcp-session-id")
            if sid:
                captured_session_ids.clear()
                captured_session_ids.append(sid)

        import httpx

        http_kwargs: dict[str, Any] = {}

        extra_headers = dict(config.headers or {})
        old_sid = state.last_session_id
        if old_sid:
            extra_headers["mcp-session-id"] = old_sid

        event_hooks: dict[str, list] = {"response": [_on_response]}
        http_timeout = httpx.Timeout(config.timeout, read=config.timeout * 2)

        if config.oauth:
            try:
                from mcp.client.auth import OAuthClientProvider
                from mcp.shared.auth import OAuthClientMetadata
                from pydantic import AnyUrl

                storage_path = self._data_dir / f"oauth_{config.name}.json"

                async def _redirect_handler(url: str) -> None:
                    logger.info("MCP OAuth: visit {}", url)

                async def _callback_handler() -> tuple[str, str | None]:
                    raise NotImplementedError(
                        f"OAuth callback not implemented for '{config.name}'. "
                        "Use 'headers' with a Bearer token instead.",
                    )

                oauth_provider = OAuthClientProvider(
                    server_url=config.url,
                    client_metadata=OAuthClientMetadata(
                        client_name=config.oauth.client_name,
                        redirect_uris=[AnyUrl(config.oauth.redirect_uri)],
                        grant_types=["authorization_code", "refresh_token"],
                        response_types=["code"],
                        scope=config.oauth.scope or None,
                    ),
                    storage=_FileTokenStorage(storage_path),
                    redirect_handler=_redirect_handler,
                    callback_handler=_callback_handler,
                )
                http_client = httpx.AsyncClient(
                    auth=oauth_provider,
                    timeout=http_timeout,
                    headers=extra_headers,
                    event_hooks=event_hooks,
                    follow_redirects=True,
                )
            except ImportError:
                logger.warning("MCP OAuth requires pydantic, falling back to headers")
                http_client = httpx.AsyncClient(
                    timeout=http_timeout,
                    headers=extra_headers,
                    event_hooks=event_hooks,
                    follow_redirects=True,
                )
        else:
            http_client = httpx.AsyncClient(
                timeout=http_timeout,
                headers=extra_headers,
                event_hooks=event_hooks,
                follow_redirects=True,
            )

        await stack.enter_async_context(http_client)
        http_kwargs["http_client"] = http_client

        read_stream, write_stream = await stack.enter_async_context(
            streamable_http_client(config.url, **http_kwargs),
        )
        state.session_id_fn = lambda: captured_session_ids[-1] if captured_session_ids else None

        kwargs = self._make_session_kwargs(state)
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream, **kwargs),
        )

        init_result = await self._initialize_with_retry(session, config)
        _extract_init_result(state, init_result)
        state.session = session

    def _make_session_kwargs(self, state: MCPServerState) -> dict[str, Any]:
        config = state.config
        from posipaka import __version__

        kwargs: dict[str, Any] = {
            "client_info": Implementation(name="posipaka", version=__version__),
            "read_timeout_seconds": config.timeout * 2,
        }

        def _logging_cb(params: Any) -> None:
            level = str(getattr(params, "level", "info")).upper()
            data = getattr(params, "data", "")
            logger.log(
                level if level in ("DEBUG", "INFO", "WARNING", "ERROR") else "DEBUG",
                "MCP [{}]: {}",
                config.name,
                data,
            )

        kwargs["logging_callback"] = _logging_cb

        def _message_handler(msg: Any) -> None:
            method = getattr(msg, "method", "")
            if method == "notifications/tools/list_changed":
                state.tools_cached_at = 0
                if self._tools_changed_callback:
                    task = asyncio.create_task(
                        self._tools_changed_callback(config.name),
                    )
                    task.add_done_callback(_log_task_exception)
            elif method == "notifications/resources/list_changed":
                state.resources = []
                state.resource_templates = []
                state.resources_cached_at = 0
                if self._resources_changed_callback:
                    task = asyncio.create_task(
                        self._resources_changed_callback(config.name),
                    )
                    task.add_done_callback(_log_task_exception)
            elif method == "notifications/prompts/list_changed":
                state.prompts = []
                state.prompts_cached_at = 0
            elif method == "notifications/progress":
                params = getattr(msg, "params", None)
                if params:
                    token = getattr(params, "progressToken", None)
                    if token:
                        state.progress[str(token)] = {
                            "progress": getattr(params, "progress", 0),
                            "total": getattr(params, "total", None),
                        }
                        if len(state.progress) > MAX_PROGRESS_ENTRIES:
                            excess = len(state.progress) - MAX_PROGRESS_ENTRIES
                            for old in list(state.progress)[:excess]:
                                del state.progress[old]
                        if self._progress_callback:
                            self._progress_callback(
                                config.name,
                                str(token),
                                getattr(params, "progress", 0),
                                getattr(params, "total", None),
                            )

        kwargs["message_handler"] = _message_handler

        async def _list_roots(ctx: Any) -> list:
            if config.roots:
                return [Root(uri=f"file://{p}", name=Path(p).name) for p in config.roots]
            return [Root(uri=f"file://{self._data_dir}", name="posipaka")]

        kwargs["list_roots_callback"] = _list_roots

        if self._sampling_callback:
            kwargs["sampling_callback"] = self._sampling_callback
        if self._elicitation_callback:
            kwargs["elicitation_callback"] = self._elicitation_callback

        task_handlers = self._build_task_handlers()
        if task_handlers:
            kwargs["experimental_task_handlers"] = task_handlers

        return kwargs

    def _build_task_handlers(self) -> Any:
        if not _MCP_AVAILABLE:
            return None
        try:
            from mcp.client.experimental.task_handlers import ExperimentalTaskHandlers
            from mcp.shared.experimental.tasks import InMemoryTaskStore
        except ImportError:
            return None

        store = InMemoryTaskStore()

        async def _augmented_elicitation(ctx, params, task_metadata):
            task = await store.create_task(task_metadata)
            if self._elicitation_callback:

                async def _complete():
                    try:
                        result = await self._elicitation_callback(ctx, params)
                        await store.store_result(task.taskId, result)
                        await store.update_task(task.taskId, status="completed")
                    except Exception:
                        from mcp.types import ElicitResult

                        await store.store_result(task.taskId, ElicitResult(action="decline"))
                        await store.update_task(task.taskId, status="completed")

                t = asyncio.create_task(_complete())
                t.add_done_callback(_log_task_exception)
            else:
                from mcp.types import ElicitResult

                await store.store_result(task.taskId, ElicitResult(action="decline"))
                await store.update_task(task.taskId, status="completed")
            from mcp.types import CreateTaskResult

            return CreateTaskResult(task=task)

        async def _get_task(ctx, params):
            task = await store.get_task(params.taskId)
            from mcp.types import GetTaskResult

            return GetTaskResult(
                taskId=task.taskId,
                status=task.status,
                createdAt=task.createdAt,
                lastUpdatedAt=task.lastUpdatedAt,
            )

        async def _get_task_result(ctx, params):
            result = await store.get_result(params.taskId)
            from mcp.types import GetTaskPayloadResult

            return GetTaskPayloadResult.model_validate(result.model_dump())

        return ExperimentalTaskHandlers(
            augmented_elicitation=_augmented_elicitation,
            get_task=_get_task,
            get_task_result=_get_task_result,
        )

    async def _initialize_with_retry(self, session: Any, config: MCPServerConfig) -> Any:
        last_error: Exception | None = None
        for attempt in range(INIT_MAX_RETRIES + 1):
            try:
                return await session.initialize()
            except Exception as e:
                last_error = e
                if attempt < INIT_MAX_RETRIES:
                    await asyncio.sleep(0.5 * (attempt + 1))
        raise last_error  # type: ignore[misc]

    async def stop_server(self, name: str) -> None:
        state = self._servers.get(name)
        if not state:
            return
        await self._cleanup_server(state)
        state.status = MCPServerStatus.STOPPED
        state.session = None
        state.session_id_fn = None
        state.last_session_id = None
        state.call_semaphore = None
        state.tools = []
        state.resources = []
        state.resource_templates = []
        state.tools_cached_at = 0
        state.resources_cached_at = 0
        state.server_capabilities = {}
        logger.info("MCP server stopped: {}", name)

    async def stop_all(self) -> None:
        tasks = [self.stop_server(name) for name in list(self._servers)]
        if tasks:
            try:
                async with asyncio.timeout(15):
                    await asyncio.gather(*tasks, return_exceptions=True)
            except TimeoutError:
                logger.warning("MCP stop_all timed out")

    async def restart_server(self, name: str) -> bool:
        state = self._servers.get(name)
        if state:
            state.consecutive_failures = 0
        await self.stop_server(name)
        return await self.start_server(name)

    async def _cleanup_server(self, state: MCPServerState) -> None:
        state.progress = {}
        if state.exit_stack:
            try:
                await state.exit_stack.aclose()
            except Exception as e:
                logger.debug("MCP cleanup error: {}", e)
            state.exit_stack = None

    async def get_tools(self, server_name: str) -> list[dict]:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.READY:
            return []

        if state.server_capabilities and "tools" not in state.server_capabilities:
            return []

        now = time_mod.time()
        if state.tools and (now - state.tools_cached_at) < TOOL_CACHE_TTL:
            return state.tools

        if not state.session:
            return state.tools

        try:

            def _tool_to_dict(t: Any) -> dict:
                d: dict[str, Any] = {
                    "name": t.name,
                    "description": getattr(t, "description", "") or "",
                    "inputSchema": getattr(t, "inputSchema", {}) or {},
                }
                ann = getattr(t, "annotations", None)
                if ann:
                    d["annotations"] = {
                        "readOnlyHint": getattr(ann, "readOnlyHint", None),
                        "destructiveHint": getattr(ann, "destructiveHint", None),
                        "idempotentHint": getattr(ann, "idempotentHint", None),
                        "openWorldHint": getattr(ann, "openWorldHint", None),
                    }
                return d

            tools = await _paginated_list(
                state.session.list_tools,
                "tools",
                _tool_to_dict,
            )
            state.tools = tools
            state.tools_cached_at = time_mod.time()
            return tools
        except _McpError:
            logger.debug("MCP protocol error listing tools for '{}'", server_name)
            return state.tools
        except Exception as e:
            logger.error("MCP get_tools error ({}): {}", server_name, e)
            state.consecutive_failures += 1
            return state.tools

    async def get_all_tools(self) -> dict[str, list[dict]]:
        ready = [name for name, s in self._servers.items() if s.status == MCPServerStatus.READY]
        if not ready:
            return {}

        results = await asyncio.gather(
            *(self.get_tools(name) for name in ready),
            return_exceptions=True,
        )
        out: dict[str, list[dict]] = {}
        for name, result in zip(ready, results):
            if isinstance(result, list):
                out[name] = result
            else:
                out[name] = self._servers[name].tools
        return out

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict,
        *,
        call_id: str | None = None,
    ) -> dict:
        state = self._servers.get(server_name)
        if not state:
            return _error_result(f"Server '{server_name}' not found")

        if state.status == MCPServerStatus.ERROR:
            if state.consecutive_failures < CIRCUIT_BREAKER_THRESHOLD:
                await self._try_reconnect(server_name)
                state = self._servers[server_name]
            if state.status != MCPServerStatus.READY:
                return _error_result(f"Server '{server_name}' in error state")

        if state.status != MCPServerStatus.READY:
            return _error_result(f"Server '{server_name}' not ready")

        if not state.session:
            return _error_result(f"Server '{server_name}': no session")

        if state.tools and tool_name not in {t.get("name") for t in state.tools}:
            return _error_result(f"Tool '{tool_name}' not found on server '{server_name}'")

        timeout = state.config.timeout or CALL_TIMEOUT
        start = time_mod.time()

        async def _do_call() -> dict:
            if state.call_semaphore:
                await state.call_semaphore.acquire()
            try:
                async with asyncio.timeout(timeout):
                    result = await state.session.call_tool(tool_name, arguments)

                content = [_content_block_to_dict(c) for c in (result.content or [])]
                is_error = getattr(result, "isError", False)
                structured = getattr(result, "structuredContent", None)

                out: dict[str, Any] = {
                    "content": content,
                    "isError": is_error,
                }
                if structured is not None:
                    out["structuredContent"] = structured
                return out
            finally:
                if state.call_semaphore:
                    state.call_semaphore.release()

        last_error: Exception | None = None
        for attempt in range(CALL_MAX_RETRIES + 1):
            call_task = asyncio.create_task(_do_call())
            if call_id:
                self._inflight[call_id] = call_task
            try:
                result = await call_task
                elapsed = (time_mod.time() - start) * 1000
                self.metrics.record(server_name, tool_name, elapsed, success=True)
                state.consecutive_failures = 0
                return result
            except asyncio.CancelledError:
                elapsed = (time_mod.time() - start) * 1000
                self.metrics.record(server_name, tool_name, elapsed, success=False)
                return _error_result(f"MCP tool call cancelled: {tool_name}")
            except _McpError as e:
                elapsed = (time_mod.time() - start) * 1000
                self.metrics.record(server_name, tool_name, elapsed, success=False)
                return _error_result(f"MCP protocol error: {e}")
            except TimeoutError:
                elapsed = (time_mod.time() - start) * 1000
                self.metrics.record(server_name, tool_name, elapsed, success=False)
                state.consecutive_failures += 1
                return _error_result(f"MCP tool timeout: {tool_name}")
            except Exception as e:
                last_error = e
                if attempt < CALL_MAX_RETRIES:
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                elapsed = (time_mod.time() - start) * 1000
                self.metrics.record(server_name, tool_name, elapsed, success=False)
                state.consecutive_failures += 1
                return _error_result(f"MCP call error: {last_error}")
            finally:
                if call_id:
                    self._inflight.pop(call_id, None)

        return _error_result(f"MCP call error: {last_error}")

    def cancel_tool_call(self, call_id: str) -> bool:
        task = self._inflight.get(call_id)
        if task:
            task.cancel()
            return True
        return False

    async def get_resources(self, server_name: str) -> list[dict]:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.READY:
            return []

        if state.server_capabilities and "resources" not in state.server_capabilities:
            return []

        now = time_mod.time()
        if state.resources and (now - state.resources_cached_at) < RESOURCE_CACHE_TTL:
            return state.resources

        if not state.session:
            return state.resources

        try:

            def _res_to_dict(r: Any) -> dict:
                return {
                    "uri": getattr(r, "uri", ""),
                    "name": getattr(r, "name", ""),
                    "description": getattr(r, "description", ""),
                    "mimeType": getattr(r, "mimeType", None),
                }

            resources = await _paginated_list(
                state.session.list_resources,
                "resources",
                _res_to_dict,
            )
            state.resources = resources
            state.resources_cached_at = time_mod.time()
            return resources
        except _McpError:
            logger.debug("MCP protocol error listing resources for '{}'", server_name)
            return state.resources
        except Exception as e:
            logger.error("MCP get_resources error ({}): {}", server_name, e)
            state.consecutive_failures += 1
            return state.resources

    async def read_resource(self, server_name: str, uri: str) -> str:
        state = self._servers.get(server_name)
        if not state:
            return ""

        if state.status == MCPServerStatus.ERROR:
            if state.consecutive_failures < CIRCUIT_BREAKER_THRESHOLD:
                await self._try_reconnect(server_name)
                state = self._servers[server_name]

        if state.status != MCPServerStatus.READY or not state.session:
            return ""

        try:
            async with asyncio.timeout(state.config.timeout or CALL_TIMEOUT):
                result = await state.session.read_resource(uri)
            texts: list[str] = []
            for c in result.contents:
                text = getattr(c, "text", None)
                blob = getattr(c, "blob", None)
                if text:
                    if len(text) > MAX_RESOURCE_SIZE:
                        text = (
                            text[:MAX_RESOURCE_SIZE] + f"\n[truncated at {MAX_RESOURCE_SIZE} bytes]"
                        )
                    texts.append(text)
                elif blob:
                    texts.append(f"[Binary: {len(blob)} bytes]")
            return "\n".join(texts)
        except Exception as e:
            logger.error("MCP read_resource error ({}): {}", server_name, e)
            state.consecutive_failures += 1
            return ""

    async def get_resource_templates(self, server_name: str) -> list[dict]:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.READY:
            return []

        if state.server_capabilities and "resources" not in state.server_capabilities:
            return []

        if not state.session:
            return []

        try:
            templates = await _paginated_list(
                state.session.list_resource_templates,
                "resourceTemplates",
                _resource_template_to_dict,
            )
            state.resource_templates = templates
            return templates
        except Exception as e:
            logger.error("MCP get_resource_templates error ({}): {}", server_name, e)
            return []

    async def subscribe_resource(self, server_name: str, uri: str) -> bool:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.READY or not state.session:
            return False
        try:
            await state.session.subscribe_resource(uri)
            return True
        except Exception as e:
            logger.error("MCP subscribe error: {}", e)
            return False

    async def unsubscribe_resource(self, server_name: str, uri: str) -> bool:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.READY or not state.session:
            return False
        try:
            await state.session.unsubscribe_resource(uri)
            return True
        except Exception as e:
            logger.error("MCP unsubscribe error: {}", e)
            return False

    async def get_prompts(self, server_name: str) -> list[dict]:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.READY:
            return []

        if state.server_capabilities and "prompts" not in state.server_capabilities:
            return []

        now = time_mod.time()
        if state.prompts and (now - state.prompts_cached_at) < PROMPT_CACHE_TTL:
            return state.prompts

        if not state.session:
            return state.prompts

        try:

            def _prompt_to_dict(p: Any) -> dict:
                args_list = []
                for a in getattr(p, "arguments", None) or []:
                    args_list.append(
                        {
                            "name": getattr(a, "name", ""),
                            "description": getattr(a, "description", ""),
                            "required": getattr(a, "required", False),
                        }
                    )
                return {
                    "name": getattr(p, "name", ""),
                    "description": getattr(p, "description", ""),
                    "arguments": args_list,
                }

            prompts = await _paginated_list(
                state.session.list_prompts,
                "prompts",
                _prompt_to_dict,
            )
            state.prompts = prompts
            state.prompts_cached_at = time_mod.time()
            return prompts
        except _McpError:
            logger.debug("MCP protocol error listing prompts for '{}'", server_name)
            return state.prompts
        except Exception as e:
            logger.error("MCP get_prompts error ({}): {}", server_name, e)
            return state.prompts

    async def get_prompt(
        self,
        server_name: str,
        prompt_name: str,
        arguments: dict[str, str] | None = None,
    ) -> dict | None:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.READY or not state.session:
            return None
        try:
            result = await state.session.get_prompt(prompt_name, arguments or {})
            messages = []
            for msg in result.messages:
                content = _prompt_content_to_str(msg.content)
                messages.append({"role": msg.role, "content": content})
            return {
                "description": getattr(result, "description", ""),
                "messages": messages,
            }
        except Exception as e:
            logger.error("MCP get_prompt error: {}", e)
            return None

    async def get_completion(
        self,
        server_name: str,
        ref_type: str,
        ref_name: str,
        argument_name: str,
        argument_value: str,
    ) -> list[str]:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.READY or not state.session:
            return []

        try:
            if ref_type == "ref/prompt":
                from mcp.types import PromptReference

                ref = PromptReference(type="ref/prompt", name=ref_name)
            elif ref_type == "ref/resource":
                from mcp.types import ResourceTemplateReference

                ref = ResourceTemplateReference(type="ref/resource", uri=ref_name)
            else:
                return []

            result = await state.session.complete(
                ref=ref,
                argument={"name": argument_name, "value": argument_value},
            )
            return result.completion.values
        except Exception as e:
            logger.error("MCP completion error: {}", e)
            return []

    async def search_tools(self, query: str, limit: int = 5) -> list[dict]:
        if not query.strip():
            return []

        words = [w.lower() for w in query.lower().split() if len(w) >= 2]
        if not words:
            return []

        all_results: list[dict] = []
        for name, state in self._servers.items():
            if state.status != MCPServerStatus.READY:
                continue

            if not state.tools and state.session:
                await self.get_tools(name)

            for tool in state.tools:
                score = _score_tool(words, query.lower(), tool)
                if score > 0:
                    all_results.append(
                        {
                            **tool,
                            "_score": score,
                            "_server": name,
                        }
                    )

        all_results.sort(key=lambda t: t["_score"], reverse=True)
        return all_results[:limit]

    async def health_check(self, server_name: str) -> bool:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.READY or not state.session:
            return False
        try:
            await state.session.send_ping()
            return True
        except Exception:
            state.status = MCPServerStatus.ERROR
            state.consecutive_failures += 1
            return False

    async def health_check_all(self) -> dict[str, bool]:
        ready = [name for name, s in self._servers.items() if s.status == MCPServerStatus.READY]
        if not ready:
            return {}

        results = await asyncio.gather(
            *(self.health_check(name) for name in ready),
            return_exceptions=True,
        )
        return {name: (r is True) for name, r in zip(ready, results)}

    async def _try_reconnect(self, server_name: str) -> bool:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.ERROR:
            return False
        if state.consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
            return False

        if state.config.transport == MCPTransport.HTTP and state.session_id_fn:
            try:
                state.last_session_id = state.session_id_fn()
            except Exception:
                pass

        logger.info("MCP: attempting reconnect for '{}'", server_name)
        await self._cleanup_server(state)
        state.status = MCPServerStatus.STOPPED

        ok = await self.start_server(server_name)
        state.last_session_id = None
        return ok

    async def reconnect_failed_servers(self) -> int:
        failed = [
            name
            for name, s in self._servers.items()
            if s.status == MCPServerStatus.ERROR
            and s.consecutive_failures < CIRCUIT_BREAKER_THRESHOLD
        ]
        if not failed:
            return 0

        results = await asyncio.gather(
            *(self._try_reconnect(name) for name in failed),
            return_exceptions=True,
        )
        return sum(1 for r in results if r is True)

    def get_server_status(self) -> list[dict]:
        statuses: list[dict] = []
        for name, state in self._servers.items():
            sid = None
            if state.session_id_fn:
                try:
                    sid = state.session_id_fn()
                except Exception:
                    pass
            per_server = self.metrics.per_server.get(name, {})
            statuses.append(
                {
                    "name": name,
                    "status": state.status.value,
                    "transport": state.config.transport.value,
                    "tools_count": len(state.tools),
                    "resources_count": len(state.resources),
                    "prompts_count": len(state.prompts),
                    "protocol_version": state.protocol_version,
                    "consecutive_failures": state.consecutive_failures,
                    "last_error": state.last_error,
                    "session_id": sid,
                    "capabilities": dict(state.server_capabilities),
                    "metrics": per_server,
                }
            )
        return statuses

    def get_session_id(self, server_name: str) -> str | None:
        state = self._servers.get(server_name)
        if not state or not state.session_id_fn:
            return None
        try:
            return state.session_id_fn()
        except Exception:
            return None

    async def call_tool_as_task(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict,
    ) -> dict | None:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.READY or not state.session:
            return None
        experimental = getattr(state.session, "experimental", None)
        if not experimental:
            return None
        try:
            result = await experimental.call_tool_as_task(tool_name, arguments)
            task_ref = result.task
            return {
                "taskId": task_ref.taskId,
                "status": task_ref.status,
            }
        except Exception as e:
            logger.error("MCP call_tool_as_task error: {}", e)
            return None

    async def get_task_status(
        self,
        server_name: str,
        task_id: str,
    ) -> dict | None:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.READY or not state.session:
            return None
        experimental = getattr(state.session, "experimental", None)
        if not experimental:
            return None
        try:
            result = await experimental.get_task(task_id)
            return {
                "taskId": task_id,
                "status": result.status,
                "statusMessage": getattr(result, "statusMessage", None),
            }
        except Exception as e:
            logger.error("MCP get_task_status error: {}", e)
            return None

    async def get_task_result(
        self,
        server_name: str,
        task_id: str,
    ) -> dict | None:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.READY or not state.session:
            return None
        experimental = getattr(state.session, "experimental", None)
        if not experimental:
            return None
        try:
            return await experimental.get_task_result(task_id)
        except Exception as e:
            logger.error("MCP get_task_result error: {}", e)
            return None

    async def cancel_task(
        self,
        server_name: str,
        task_id: str,
    ) -> bool:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.READY or not state.session:
            return False
        experimental = getattr(state.session, "experimental", None)
        if not experimental:
            return False
        try:
            await experimental.cancel_task(task_id)
            return True
        except Exception as e:
            logger.error("MCP cancel_task error: {}", e)
            return False

    async def poll_task_until_done(
        self,
        server_name: str,
        task_id: str,
        *,
        timeout: float = 300.0,
    ) -> dict | None:
        state = self._servers.get(server_name)
        if not state or state.status != MCPServerStatus.READY or not state.session:
            return None

        experimental = getattr(state.session, "experimental", None)
        if not experimental or not hasattr(experimental, "poll_task"):
            return None

        try:
            async with asyncio.timeout(timeout):
                async for status in experimental.poll_task(task_id):
                    st = getattr(status, "status", "")
                    if st in ("completed", "input_required"):
                        return await self.get_task_result(server_name, task_id)
                    if st in ("failed", "cancelled"):
                        return {
                            "taskId": task_id,
                            "status": st,
                            "statusMessage": getattr(status, "statusMessage", ""),
                        }
        except TimeoutError:
            logger.warning("MCP poll_task timed out for {}/{}", server_name, task_id)
        except Exception as e:
            logger.error("MCP poll_task error: {}", e)
        return None
