"""Posipaka — Shell Integration. Виконання shell команд та робота з файлами."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from posipaka.security.filesystem_policy import AccessDecision, FilesystemPolicy
from posipaka.security.sandbox import ShellSandbox

_sandbox = ShellSandbox()
_fs_policy = FilesystemPolicy()


async def shell_exec(command: str, working_dir: str = "", timeout: int = 30) -> str:
    """Виконати shell команду в sandbox."""
    sandbox = ShellSandbox(timeout=timeout)
    result = await sandbox.execute(command, working_dir or None)
    if result.blocked:
        return f"Команду заблоковано: {result.blocked_reason}"
    if result.timed_out:
        return f"Timeout: команда не завершилась за {timeout}s"
    output = result.stdout
    if result.stderr:
        output += f"\nSTDERR: {result.stderr}"
    if result.return_code != 0:
        output += f"\n(exit code: {result.return_code})"
    return output.strip() or "(порожній вивід)"


async def python_exec(code: str) -> str:
    """Виконати Python код."""
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        f.flush()
        try:
            result = await _sandbox.execute(f"python3 {f.name}")
            if result.blocked:
                return f"Заблоковано: {result.blocked_reason}"
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            return output.strip() or "(порожній вивід)"
        finally:
            os.unlink(f.name)


async def read_file(path: str, max_lines: int = 200) -> str:
    """Прочитати файл."""
    try:
        from posipaka.security.path_traversal import validate_path

        safe, reason = validate_path(path)
        if not safe:
            return f"Доступ заблоковано: {reason}"

        # FilesystemPolicy check (секція 97 MASTER.md)
        decision = _fs_policy.check_path(path, "read")
        if decision == AccessDecision.DENY_HARD:
            return f"Доступ заборонено політикою: {path}"
        if decision == AccessDecision.REQUIRE_APPROVAL:
            return f"Потрібне підтвердження для читання: {path}"

        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"Файл не знайдено: {path}"
        if not p.is_file():
            return f"Це не файл: {path}"
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if len(lines) > max_lines:
            return "\n".join(lines[:max_lines]) + f"\n... (ще {len(lines) - max_lines} рядків)"
        return text
    except Exception as e:
        return f"Помилка читання: {e}"


async def write_file(path: str, content: str) -> str:
    """Записати файл (requires approval якщо поза /tmp)."""
    try:
        # FilesystemPolicy check (секція 97 MASTER.md)
        decision = _fs_policy.check_path(path, "write")
        if decision == AccessDecision.DENY_HARD:
            return f"Запис заборонено політикою: {path}"

        p = Path(path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Записано {len(content)} символів у {path}"
    except Exception as e:
        return f"Помилка запису: {e}"


async def list_directory(path: str = ".") -> str:
    """Список файлів у директорії."""
    try:
        # FilesystemPolicy check (секція 97 MASTER.md)
        decision = _fs_policy.check_path(path, "read")
        if decision == AccessDecision.DENY_HARD:
            return f"Доступ заборонено політикою: {path}"

        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"Директорія не існує: {path}"
        if not p.is_dir():
            return f"Це не директорія: {path}"
        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = []
        for entry in entries[:100]:
            prefix = "📁" if entry.is_dir() else "📄"
            size = ""
            if entry.is_file():
                s = entry.stat().st_size
                if s < 1024:
                    size = f" ({s} B)"
                elif s < 1024 * 1024:
                    size = f" ({s // 1024} KB)"
                else:
                    size = f" ({s // (1024 * 1024)} MB)"
            lines.append(f"{prefix} {entry.name}{size}")
        result = "\n".join(lines)
        if len(entries) > 100:
            result += f"\n... та ще {len(entries) - 100} файлів"
        return result
    except Exception as e:
        return f"Помилка: {e}"


def register(registry: Any) -> None:
    """Реєстрація shell tools."""
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="shell_exec",
            description=(
                "Execute a shell command."
                " Use for system operations, running scripts, checking system info."
            ),
            category="integration",
            handler=shell_exec,
            input_schema={
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "working_dir": {
                        "type": "string",
                        "description": "Working directory (optional)",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 30)",
                    },
                },
            },
            tags=["shell", "system"],
        )
    )

    registry.register(
        ToolDefinition(
            name="python_exec",
            description="Execute Python code. Use for calculations, data processing, scripting.",
            category="integration",
            handler=python_exec,
            input_schema={
                "type": "object",
                "required": ["code"],
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                },
            },
            tags=["shell", "python"],
        )
    )

    registry.register(
        ToolDefinition(
            name="read_file",
            description="Read a file from the filesystem. Use to view file contents.",
            category="integration",
            handler=read_file,
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "max_lines": {
                        "type": "integer",
                        "description": "Max lines to read (default 200)",
                    },
                },
            },
            tags=["shell", "file"],
        )
    )

    registry.register(
        ToolDefinition(
            name="write_file",
            description="Write content to a file. WARNING: this modifies the filesystem.",
            category="integration",
            handler=write_file,
            input_schema={
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "File content"},
                },
            },
            requires_approval=True,
            tags=["shell", "file"],
        )
    )

    registry.register(
        ToolDefinition(
            name="list_directory",
            description="List files and folders in a directory.",
            category="integration",
            handler=list_directory,
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default: current)"},
                },
            },
            tags=["shell", "file"],
        )
    )
