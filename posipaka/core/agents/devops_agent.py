"""DevOpsAgent — серверне адміністрування, Docker, деплоймент."""

from __future__ import annotations

from loguru import logger

from posipaka.core.agents.base import AgentTask, BaseSpecializedAgent


class DevOpsAgent(BaseSpecializedAgent):
    """Агент для DevOps: shell, Docker, системне адміністрування."""

    @property
    def name(self) -> str:
        return "devops"

    @property
    def description(self) -> str:
        return "Server administration, Docker, deployment, system monitoring"

    @property
    def capabilities(self) -> list[str]:
        return [
            "server",
            "deploy",
            "docker",
            "systemd",
            "nginx",
            "ssl",
            "firewall",
            "monitor",
            "disk",
            "memory",
            "cpu",
            "process",
            "сервер",
            "деплой",
            "моніторинг",
            "logs",
            "service",
            "container",
        ]

    async def execute(self, task: AgentTask) -> str:
        try:
            from posipaka.integrations.shell.tools import shell_exec

            lower = task.description.lower()

            if "disk" in lower or "диск" in lower:
                return await shell_exec("df -h")
            elif "memory" in lower or "пам'ять" in lower or "ram" in lower:
                return await shell_exec("free -h")
            elif "cpu" in lower or "процес" in lower:
                return await shell_exec("top -bn1 | head -20")
            elif "docker" in lower:
                return await shell_exec(
                    "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
                )
            elif "log" in lower:
                return await shell_exec("journalctl --no-pager -n 50")
            elif "uptime" in lower or "аптайм" in lower:
                return await shell_exec("uptime")
            else:
                # General system info
                return await shell_exec(
                    "echo '=== System ===' && uname -a && "
                    "echo '=== Uptime ===' && uptime && "
                    "echo '=== Memory ===' && free -h && "
                    "echo '=== Disk ===' && df -h /"
                )
        except Exception as e:
            logger.error(f"DevOpsAgent error: {e}")
            return f"Помилка DevOpsAgent: {e}"
