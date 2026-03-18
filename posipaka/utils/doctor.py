"""posipaka doctor — діагностика системи."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path


class DoctorCheck:
    """Одна перевірка."""

    def __init__(self, name: str, status: str, message: str) -> None:
        self.name = name
        self.status = status  # ok | warning | error
        self.message = message

    def __str__(self) -> str:
        icons = {"ok": "OK", "warning": "WARN", "error": "FAIL"}
        return f"[{icons.get(self.status, '?')}] {self.name}: {self.message}"


def run_doctor(data_dir: Path | None = None) -> list[DoctorCheck]:
    """Запустити всі діагностичні перевірки."""
    checks: list[DoctorCheck] = []
    data_dir = data_dir or Path.home() / ".posipaka"

    # Python version
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 11):  # noqa: UP036
        checks.append(DoctorCheck("Python", "ok", ver))
    else:
        checks.append(DoctorCheck("Python", "error", f"{ver} (потрібен 3.11+)"))

    # OS
    checks.append(
        DoctorCheck(
            "OS", "ok", f"{platform.system()} {platform.release()}"
        )
    )

    # Disk space
    disk = shutil.disk_usage(Path.home())
    free_gb = disk.free / (1024**3)
    if free_gb > 5:
        checks.append(DoctorCheck("Disk", "ok", f"{free_gb:.1f} GB free"))
    elif free_gb > 1:
        checks.append(
            DoctorCheck("Disk", "warning", f"{free_gb:.1f} GB free (low)")
        )
    else:
        checks.append(
            DoctorCheck(
                "Disk", "error", f"{free_gb:.1f} GB free (critical!)"
            )
        )

    # RAM
    try:
        import psutil

        ram = psutil.virtual_memory()
        ram_gb = ram.total / (1024**3)
        checks.append(
            DoctorCheck(
                "RAM",
                "ok" if ram_gb >= 1 else "warning",
                f"{ram_gb:.1f} GB total, {ram.percent}% used",
            )
        )
    except ImportError:
        checks.append(DoctorCheck("RAM", "warning", "psutil not installed"))

    # Data directory
    if data_dir.exists():
        checks.append(DoctorCheck("Data dir", "ok", str(data_dir)))
    else:
        checks.append(
            DoctorCheck(
                "Data dir",
                "warning",
                f"{data_dir} not found (run posipaka setup)",
            )
        )

    # Key files
    for name, filename in [
        ("SOUL.md", "SOUL.md"),
        ("Config", "config.yaml"),
        ("Audit log", "audit.log"),
    ]:
        path = data_dir / filename
        if path.exists():
            size = path.stat().st_size
            checks.append(
                DoctorCheck(name, "ok", f"{size} bytes")
            )
        else:
            checks.append(DoctorCheck(name, "warning", "not found"))

    # SQLite DB
    db_path = data_dir / "memory.db"
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        checks.append(DoctorCheck("Memory DB", "ok", f"{size_mb:.1f} MB"))
    else:
        checks.append(DoctorCheck("Memory DB", "warning", "not found"))

    # Docker
    if shutil.which("docker"):
        checks.append(DoctorCheck("Docker", "ok", "available"))
    else:
        checks.append(DoctorCheck("Docker", "warning", "not installed"))

    # Key packages
    for pkg_name in ["anthropic", "httpx", "fastapi", "rich", "pydantic"]:
        try:
            __import__(pkg_name)
            checks.append(DoctorCheck(f"pkg:{pkg_name}", "ok", "installed"))
        except ImportError:
            checks.append(
                DoctorCheck(f"pkg:{pkg_name}", "error", "not installed")
            )

    # Optional packages
    for pkg_name in [
        "chromadb",
        "sentence_transformers",
        "telegram",
        "playwright",
    ]:
        try:
            __import__(pkg_name)
            checks.append(
                DoctorCheck(f"opt:{pkg_name}", "ok", "installed")
            )
        except ImportError:
            checks.append(
                DoctorCheck(f"opt:{pkg_name}", "warning", "not installed")
            )

    # .env file
    env_path = data_dir / ".env"
    if env_path.exists():
        checks.append(DoctorCheck(".env", "ok", "exists"))
    elif Path(".env").exists():
        checks.append(DoctorCheck(".env", "ok", "in project root"))
    else:
        checks.append(DoctorCheck(".env", "warning", "not found"))

    # LLM API key
    has_key = bool(
        os.environ.get("LLM_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )
    if has_key:
        checks.append(DoctorCheck("LLM API key", "ok", "set"))
    else:
        checks.append(
            DoctorCheck("LLM API key", "warning", "not set in env")
        )

    return checks


def format_doctor_report(checks: list[DoctorCheck]) -> str:
    """Форматувати звіт."""
    lines = ["Posipaka Doctor Report", "=" * 40]
    ok = sum(1 for c in checks if c.status == "ok")
    warn = sum(1 for c in checks if c.status == "warning")
    err = sum(1 for c in checks if c.status == "error")

    for check in checks:
        lines.append(str(check))

    lines.append("")
    lines.append(f"Summary: {ok} OK, {warn} warnings, {err} errors")

    if err > 0:
        lines.append("Fix errors before running posipaka.")
    elif warn > 0:
        lines.append("Warnings won't prevent running but may limit features.")
    else:
        lines.append("All checks passed!")

    return "\n".join(lines)
