"""Resource Permission Matrix — гранулярні права."""

from __future__ import annotations

from enum import StrEnum


class ResourcePermission(StrEnum):
    """Всі можливі дозволи до ресурсів системи."""

    # Файлова система
    FS_READ_WORKSPACE = "fs.read.workspace"
    FS_READ_HOME = "fs.read.home"
    FS_READ_SYSTEM = "fs.read.system"
    FS_WRITE_WORKSPACE = "fs.write.workspace"
    FS_WRITE_HOME = "fs.write.home"
    FS_WRITE_TEMP = "fs.write.temp"
    FS_WRITE_SYSTEM = "fs.write.system"
    FS_EXECUTE = "fs.execute"

    # Shell
    SHELL_SAFE_COMMANDS = "shell.safe"
    SHELL_PACKAGE_MANAGER = "shell.pkg"
    SHELL_NETWORK_TOOLS = "shell.network"
    SHELL_PROCESS_CONTROL = "shell.process"
    SHELL_SYSTEM_CONTROL = "shell.system"
    SHELL_DESTRUCTIVE = "shell.destructive"
    SHELL_ARBITRARY = "shell.arbitrary"

    # Мережа
    NET_INTERNET = "net.internet"
    NET_LOCAL = "net.local"
    NET_PRIVATE_RANGES = "net.private"

    # Процеси
    PROC_READ = "proc.read"
    PROC_SPAWN = "proc.spawn"
    PROC_KILL = "proc.kill"

    # Системні
    SYS_ENV_READ = "sys.env.read"
    SYS_ENV_WRITE = "sys.env.write"

    # Інтеграції
    INTEGRATION_EMAIL_READ = "integration.email.read"
    INTEGRATION_EMAIL_SEND = "integration.email.send"
    INTEGRATION_CALENDAR_READ = "integration.calendar.read"
    INTEGRATION_CALENDAR_WRITE = "integration.calendar.write"
    INTEGRATION_GITHUB = "integration.github"
    INTEGRATION_BROWSER = "integration.browser"
    INTEGRATION_HOME_ASSISTANT = "integration.homeassistant"


_MINIMAL: frozenset[ResourcePermission] = frozenset(
    {
        ResourcePermission.FS_READ_WORKSPACE,
        ResourcePermission.FS_WRITE_WORKSPACE,
        ResourcePermission.FS_WRITE_TEMP,
        ResourcePermission.NET_INTERNET,
        ResourcePermission.INTEGRATION_BROWSER,
    }
)

_STANDARD: frozenset[ResourcePermission] = frozenset(
    {
        *_MINIMAL,
        ResourcePermission.FS_READ_HOME,
        ResourcePermission.SHELL_SAFE_COMMANDS,
        ResourcePermission.SHELL_PACKAGE_MANAGER,
        ResourcePermission.SHELL_NETWORK_TOOLS,
        ResourcePermission.NET_LOCAL,
        ResourcePermission.PROC_READ,
        ResourcePermission.PROC_SPAWN,
        ResourcePermission.SYS_ENV_READ,
        ResourcePermission.INTEGRATION_EMAIL_READ,
        ResourcePermission.INTEGRATION_EMAIL_SEND,
        ResourcePermission.INTEGRATION_CALENDAR_READ,
        ResourcePermission.INTEGRATION_CALENDAR_WRITE,
        ResourcePermission.INTEGRATION_GITHUB,
    }
)

_DEVELOPER: frozenset[ResourcePermission] = frozenset(
    {
        *_STANDARD,
        ResourcePermission.FS_WRITE_HOME,
        ResourcePermission.FS_EXECUTE,
        ResourcePermission.SHELL_PROCESS_CONTROL,
        ResourcePermission.SHELL_SYSTEM_CONTROL,
        ResourcePermission.PROC_KILL,
        ResourcePermission.SYS_ENV_WRITE,
        ResourcePermission.INTEGRATION_HOME_ASSISTANT,
    }
)

_DOCKER: frozenset[ResourcePermission] = frozenset(
    {
        ResourcePermission.FS_READ_WORKSPACE,
        ResourcePermission.FS_WRITE_WORKSPACE,
        ResourcePermission.FS_WRITE_TEMP,
        ResourcePermission.SHELL_SAFE_COMMANDS,
        ResourcePermission.SHELL_NETWORK_TOOLS,
        ResourcePermission.NET_INTERNET,
        ResourcePermission.NET_LOCAL,
        ResourcePermission.PROC_READ,
        ResourcePermission.PROC_SPAWN,
        ResourcePermission.INTEGRATION_BROWSER,
        ResourcePermission.INTEGRATION_EMAIL_READ,
        ResourcePermission.INTEGRATION_EMAIL_SEND,
        ResourcePermission.INTEGRATION_CALENDAR_READ,
        ResourcePermission.INTEGRATION_CALENDAR_WRITE,
    }
)

PERMISSION_PROFILES: dict[str, frozenset[ResourcePermission]] = {
    "minimal": _MINIMAL,
    "standard": _STANDARD,
    "developer": _DEVELOPER,
    "full": frozenset(ResourcePermission),
    "docker": _DOCKER,
}


def get_profile(name: str) -> frozenset[ResourcePermission]:
    return PERMISSION_PROFILES.get(name, _STANDARD)


def check_permission(
    profile: str,
    permission: ResourcePermission,
    custom_overrides: dict[str, bool] | None = None,
) -> bool:
    """Перевірити чи дозвіл увімкнений."""
    if custom_overrides and permission.value in custom_overrides:
        return custom_overrides[permission.value]
    return permission in get_profile(profile)
