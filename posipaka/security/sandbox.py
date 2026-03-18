"""ShellSandbox — Рівень 1 software sandbox (секція 33.2 MASTER.md)."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass

from loguru import logger


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    return_code: int
    timed_out: bool = False
    blocked: bool = False
    blocked_reason: str = ""
    execution_ms: float = 0.0


class ShellSandbox:
    """
    Рівень 1: Software sandbox для shell_exec та python_exec.

    Принцип: навіть якщо LLM згенерував шкідливу команду —
    sandbox або заблокує її, або обмежить шкоду.
    """

    DEFAULT_TIMEOUT = 30
    MAX_OUTPUT_SIZE = 50_000

    # Бінарники дозволені БЕЗ approval
    ALLOWED_BINS: frozenset[str] = frozenset(
        [
            "python",
            "python3",
            "pip",
            "pip3",
            "ls",
            "cat",
            "grep",
            "find",
            "echo",
            "pwd",
            "date",
            "whoami",
            "head",
            "tail",
            "wc",
            "sort",
            "uniq",
            "cut",
            "awk",
            "sed",
            "mkdir",
            "touch",
            "cp",
            "mv",
            "git",
            "curl",
            "wget",
            "jq",
            "uname",
            "df",
            "du",
            "free",
            "ps",
            "top",
            "uptime",
            "node",
            "npm",
            "npx",
        ]
    )

    # Патерни що ЗАВЖДИ блокуються
    HARD_BLOCKED: list[tuple[str, str]] = [
        (r"rm\s+-[rf]+\s+/", "rm -rf /"),
        (r":\(\)\s*\{.*\|.*&\s*\}\s*;", "fork bomb"),
        (r">\s*/dev/(sda|hda|nvme)", "write to block device"),
        (r"dd\s+if=.*of=/dev/", "dd to device"),
        (r"mkfs\.", "format filesystem"),
        (r"chmod\s+(777|a\+x)\s+/", "chmod 777 on root"),
        (r"curl.*\|\s*(bash|sh)", "curl pipe to bash"),
        (r"wget.*\|\s*(bash|sh)", "wget pipe to bash"),
        (r"python.*-c.*__import__.*os.*system", "python -c bypass"),
        (r"base64.*-d.*\|.*(bash|sh)", "base64 decode pipe"),
        (r"eval\s+\$\(", "eval injection"),
    ]

    # Команди що завжди блоковані
    BLOCKED_COMMANDS: frozenset[str] = frozenset(
        ["shutdown", "reboot", "halt", "poweroff", "init", "telinit"]
    )

    # Патерни що вимагають approval (не блокуємо, а позначаємо)
    APPROVAL_PATTERNS: list[str] = [
        r"\brm\b",
        r"\bchmod\b",
        r"\bcrontab\b",
        r"\bkill\b",
        r"\bpkill\b",
        r"\bsudo\b",
        r"\bsu\b",
        r"\biptables\b",
        r"\bufw\b",
    ]

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        max_output: int = MAX_OUTPUT_SIZE,
    ) -> None:
        self.timeout = timeout
        self.max_output = max_output

    def check_command(self, command: str) -> tuple[bool, str]:
        """Перевірити команду. Returns (safe, reason)."""
        if not command.strip():
            return False, "Порожня команда"

        first_word = command.strip().split()[0].split("/")[-1]

        # Blocked commands
        if first_word in self.BLOCKED_COMMANDS:
            return False, f"Команда '{first_word}' заблокована"

        # Hard-blocked patterns
        for pattern, description in self.HARD_BLOCKED:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"Деструктивна команда: {description}"

        return True, "ok"

    def needs_approval(self, command: str) -> str | None:
        """Перевірити чи команда потребує approval. Returns reason або None."""
        for pattern in self.APPROVAL_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return f"Команда потребує підтвердження: {pattern}"
        return None

    async def execute(
        self,
        command: str,
        working_dir: str | None = None,
        env_override: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Виконати команду з повним sandboxing."""
        start = time.monotonic()

        # 1. Hard block
        safe, reason = self.check_command(command)
        if not safe:
            logger.warning(f"Blocked: {command} — {reason}")
            return SandboxResult(
                stdout="",
                stderr=reason,
                return_code=-1,
                blocked=True,
                blocked_reason=reason,
                execution_ms=0.0,
            )

        # 2. Safe environment (без секретів)
        safe_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "TMPDIR": "/tmp",
            "LANG": "en_US.UTF-8",
        }
        if env_override:
            safe_env.update(env_override)
        # КРИТИЧНО: не передаємо API ключі
        for key in (
            "ANTHROPIC_API_KEY",
            "LLM_API_KEY",
            "OPENAI_API_KEY",
            "TELEGRAM_TOKEN",
            "GOOGLE_TOKEN",
            "GITHUB_TOKEN",
            "SLACK_BOT_TOKEN",
        ):
            safe_env.pop(key, None)

        # 3. Execute
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir or "/tmp",
                env=safe_env,
                preexec_fn=self._set_resource_limits,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=self.timeout
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                return SandboxResult(
                    stdout="",
                    stderr=f"Timeout: {self.timeout}s",
                    return_code=-1,
                    timed_out=True,
                    execution_ms=(time.monotonic() - start) * 1000,
                )
        except Exception as e:
            return SandboxResult(
                stdout="",
                stderr=str(e),
                return_code=-1,
                execution_ms=(time.monotonic() - start) * 1000,
            )

        # 4. Output truncation
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if len(stdout) > self.max_output:
            stdout = (
                stdout[: self.max_output]
                + f"\n...[TRUNCATED: {len(stdout)} chars]"
            )
        if len(stderr) > 5000:
            stderr = stderr[:5000] + "\n...[TRUNCATED]"

        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            return_code=process.returncode or 0,
            execution_ms=(time.monotonic() - start) * 1000,
        )

    @staticmethod
    def _set_resource_limits() -> None:
        """Запускається у дочірньому процесі перед exec (Linux only)."""
        try:
            import resource

            # 256MB RAM
            resource.setrlimit(
                resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024)
            )
            # 30s CPU
            resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
            # 1000 open files
            resource.setrlimit(resource.RLIMIT_NOFILE, (1000, 1000))
            # 100 processes
            resource.setrlimit(resource.RLIMIT_NPROC, (100, 100))
            # 100MB max file size
            resource.setrlimit(
                resource.RLIMIT_FSIZE, (100 * 1024 * 1024, 100 * 1024 * 1024)
            )
        except (ImportError, OSError):
            pass  # Windows or unsupported platform
