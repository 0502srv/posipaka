"""Container Sandbox — Рівень 2 ізоляції через Docker (секція 33.3 MASTER.md)."""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from pathlib import Path

from loguru import logger

from posipaka.security.sandbox import SandboxResult


class ContainerSandbox:
    """
    Рівень 2: Docker container sandbox для code execution.

    Вмикається через: SECURITY_CONTAINER_SANDBOX=true
    Потребує: Docker + (опціонально) gVisor

    Архітектура:
    1. Зберігаємо код у тимчасовий файл
    2. Запускаємо одноразовий Docker контейнер
    3. network_mode: none — без мережі
    4. read_only: true — тільки /tmp для запису
    5. Повертаємо stdout/stderr
    """

    SANDBOX_IMAGE = "python:3.12-slim"

    def __init__(
        self,
        image: str = SANDBOX_IMAGE,
        gvisor_enabled: bool = False,
        memory_limit: str = "256m",
        cpu_limit: str = "0.5",
        timeout: int = 30,
    ) -> None:
        self._image = image
        self._gvisor = gvisor_enabled
        self._memory_limit = memory_limit
        self._cpu_limit = cpu_limit
        self._timeout = timeout

    async def is_available(self) -> bool:
        """Перевірити чи Docker доступний."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            return proc.returncode == 0
        except FileNotFoundError:
            return False

    async def execute_python(self, code: str) -> SandboxResult:
        """Виконати Python код в ізольованому контейнері."""
        import time

        start = time.monotonic()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(code)
            code_file = f.name

        container_name = f"posipaka_sandbox_{uuid.uuid4().hex[:8]}"

        cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:size=64m",
            "--memory",
            self._memory_limit,
            "--memory-swap",
            self._memory_limit,
            "--cpus",
            self._cpu_limit,
            "--pids-limit",
            "50",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534",
        ]

        if self._gvisor:
            cmd.extend(["--runtime", "runsc"])

        cmd.extend(
            [
                "-v",
                f"{code_file}:/code.py:ro",
                self._image,
                "python3",
                "/code.py",
            ]
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self._timeout + 5
                )
                timed_out = False
            except TimeoutError:
                await asyncio.create_subprocess_exec(
                    "docker", "kill", container_name
                )
                timed_out = True
                stdout_bytes, stderr_bytes = b"", b"[killed: timeout]"

            elapsed = (time.monotonic() - start) * 1000

            return SandboxResult(
                stdout=stdout_bytes.decode("utf-8", errors="replace")[:50_000],
                stderr=stderr_bytes.decode("utf-8", errors="replace")[:5_000],
                return_code=proc.returncode or 0,
                timed_out=timed_out,
                execution_ms=elapsed,
            )
        except FileNotFoundError:
            return SandboxResult(
                stdout="",
                stderr="Docker not found",
                return_code=-1,
            )
        except Exception as e:
            logger.error(f"Container sandbox error: {e}")
            return SandboxResult(
                stdout="",
                stderr=str(e),
                return_code=-1,
            )
        finally:
            Path(code_file).unlink(missing_ok=True)

    async def execute_shell(self, command: str) -> SandboxResult:
        """Виконати shell команду в контейнері."""
        return await self.execute_python(
            f"import subprocess; r = subprocess.run({command!r}, "
            f"shell=True, capture_output=True, text=True, timeout=25); "
            f"print(r.stdout); "
            f"import sys; print(r.stderr, file=sys.stderr)"
        )
