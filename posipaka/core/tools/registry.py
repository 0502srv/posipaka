"""ToolRegistry — pluggable система інструментів."""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class ToolDefinition:
    """Визначення інструменту."""

    name: str
    description: str
    category: str  # "integration" | "skill" | "builtin"
    handler: Callable
    input_schema: dict
    skill_md_path: Path | None = None
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    requires_approval: bool = False

    def to_anthropic_schema(self) -> dict:
        """Формат для Anthropic API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def to_openai_schema(self) -> dict:
        """Формат для OpenAI API."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class ToolNotFoundError(Exception):
    pass


class ToolDisabledError(Exception):
    pass


class ToolPermissionError(Exception):
    pass


class ToolRegistry:
    """Реєстрація та виконання інструментів."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._permission_checker = None  # PermissionChecker (Phase 32)

    def set_permission_checker(self, checker) -> None:
        """Встановити PermissionChecker для перевірки дозволів."""
        self._permission_checker = checker

    def register(self, tool_def: ToolDefinition) -> None:
        """Зареєструвати інструмент."""
        if tool_def.name in self._tools:
            logger.warning(f"Tool '{tool_def.name}' already registered, overwriting")
        self._tools[tool_def.name] = tool_def
        logger.debug(f"Registered tool: {tool_def.name} [{tool_def.category}]")

    def tool(
        self,
        name: str,
        description: str,
        input_schema: dict,
        category: str = "builtin",
        requires_approval: bool = False,
        tags: list[str] | None = None,
    ) -> Callable:
        """Decorator для реєстрації tool."""

        def decorator(func: Callable) -> Callable:
            self.register(
                ToolDefinition(
                    name=name,
                    description=description,
                    category=category,
                    handler=func,
                    input_schema=input_schema,
                    requires_approval=requires_approval,
                    tags=tags or [],
                )
            )
            return func

        return decorator

    async def execute(self, name: str, input_data: dict, user_id: str = "") -> Any:
        """Виконати інструмент за ім'ям.

        Phase 32: перевірка дозволів перед виконанням.
        """
        if name not in self._tools:
            raise ToolNotFoundError(f"Tool '{name}' not found")

        tool_def = self._tools[name]
        if not tool_def.enabled:
            raise ToolDisabledError(f"Tool '{name}' is disabled")

        # Permission check (Phase 32)
        if self._permission_checker and user_id:
            allowed = await self._permission_checker.check(
                user_id, "TOOL_EXEC", resource=name
            )
            if not allowed:
                raise ToolPermissionError(
                    f"Tool '{name}' not permitted for user {user_id}"
                )

        handler = tool_def.handler
        if inspect.iscoroutinefunction(handler):
            return await handler(**input_data)
        return handler(**input_data)

    def get(self, name: str) -> ToolDefinition | None:
        """Отримати ToolDefinition."""
        return self._tools.get(name)

    def get_schemas(self, provider: str = "anthropic") -> list[dict]:
        """Отримати schemas для LLM API."""
        schemas = []
        for tool in self._tools.values():
            if not tool.enabled:
                continue
            if provider == "anthropic":
                schemas.append(tool.to_anthropic_schema())
            elif provider == "openai":
                schemas.append(tool.to_openai_schema())
        return schemas

    def get_skill_metadata(self) -> str:
        """Metadata для system prompt."""
        lines = ["Available tools:"]
        for tool in self._tools.values():
            if not tool.enabled:
                continue
            approval = " [requires approval]" if tool.requires_approval else ""
            lines.append(f"- {tool.name}: {tool.description}{approval}")
        return "\n".join(lines)

    def list_tools(self) -> list[dict]:
        """Список всіх tools."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "enabled": t.enabled,
                "requires_approval": t.requires_approval,
                "tags": t.tags,
            }
            for t in self._tools.values()
        ]

    def describe_action(self, name: str, input_data: dict) -> str:
        """Людино-зрозумілий опис дії для approval."""
        tool = self._tools.get(name)
        if not tool:
            return f"Unknown action: {name}"
        params = ", ".join(f"{k}={v!r}" for k, v in input_data.items())
        return f"{tool.description}\nParameters: {params}"

    def enable(self, name: str) -> None:
        if name in self._tools:
            self._tools[name].enabled = True

    def disable(self, name: str) -> None:
        if name in self._tools:
            self._tools[name].enabled = False

    def load_integration(self, name: str) -> None:
        """Динамічно завантажити інтеграцію за ім'ям."""
        try:
            module = importlib.import_module(f"posipaka.integrations.{name}.tools")
            if hasattr(module, "register"):
                module.register(self)
                logger.info(f"Loaded integration: {name}")
            else:
                logger.warning(f"Integration '{name}' has no register() function")
        except ImportError as e:
            logger.debug(f"Integration '{name}' not available: {e}")
        except Exception as e:
            logger.error(f"Error loading integration '{name}': {e}")

    def load_all_integrations(self) -> None:
        """Auto-discovery всіх інтеграцій."""
        integrations_dir = Path(__file__).parent.parent.parent / "integrations"
        if not integrations_dir.exists():
            return
        for path in integrations_dir.iterdir():
            if path.is_dir() and (path / "tools.py").exists():
                self.load_integration(path.name)

    def load_skill_dir(self, path: Path) -> None:
        """Завантажити skill з директорії."""
        tools_py = path / "tools.py"
        if not tools_py.exists():
            return
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location(f"skill_{path.name}", str(tools_py))
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if hasattr(module, "register"):
                    module.register(self)
                    logger.info(f"Loaded skill: {path.name}")
        except Exception as e:
            logger.error(f"Error loading skill '{path.name}': {e}")
