"""Security auditing, secret scanning, vulnerability detection."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from posipaka.core.agents.base import AgentTask, BaseSpecializedAgent


class SecurityAgent(BaseSpecializedAgent):
    @property
    def name(self) -> str:
        return "security"

    @property
    def description(self) -> str:
        return "Security auditing, secret scanning, vulnerability detection"

    @property
    def capabilities(self) -> list[str]:
        return [
            "security",
            "secret",
            "scan",
            "audit",
            "vulnerability",
            "leak",
            "credential",
            "безпека",
            "секрети",
            "аудит",
            "сканування",
            "вразливість",
        ]

    async def execute(self, task: AgentTask) -> str:
        try:
            desc = task.description.lower()

            if "audit" in desc or "аудит" in desc:
                return await self._run_audit()

            if "scan" in desc or "secret" in desc or "секрет" in desc:
                return await self._run_secret_scan()

            if "hygiene" in desc or "гігієна" in desc:
                return await self._run_hygiene()

            if "history" in desc or "історія" in desc or "commit" in desc:
                return await self._run_history_audit()

            # default: run all checks
            results: list[str] = []

            audit_result = await self._run_audit()
            results.append(f"## Audit\n{audit_result}")

            scan_result = await self._run_secret_scan()
            results.append(f"## Secret Scan\n{scan_result}")

            hygiene_result = await self._run_hygiene()
            results.append(f"## Hygiene\n{hygiene_result}")

            return "\n\n".join(results)

        except Exception as e:
            logger.error(f"SecurityAgent error: {e}")
            return f"Помилка SecurityAgent: {e}"

    async def _run_audit(self) -> str:
        from posipaka.security.audit import AuditLogger

        audit = AuditLogger(Path.home() / ".posipaka" / "audit.log")
        is_valid, count, message = audit.verify_integrity()
        status = "OK" if is_valid else "FAILED"
        return f"Audit integrity: {status} — {message}"

    async def _run_secret_scan(self) -> str:
        from posipaka.skills.builtin.git_helper.tools import git_secret_scan

        return await git_secret_scan(".")

    async def _run_hygiene(self) -> str:
        from posipaka.skills.builtin.git_helper.tools import repo_hygiene_check

        return await repo_hygiene_check(".")

    async def _run_history_audit(self) -> str:
        from posipaka.skills.builtin.git_helper.tools import git_history_audit

        return await git_history_audit(repo_path=".", depth=50)
