"""Auto-update mechanism.

Перевірка нових версій через GitHub Releases API,
завантаження та встановлення через pip з підтвердженням
користувача.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]


# ── Semver parsing ───────────────────────────────────────────

_SEMVER_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)"
    r"(?:-([\w.]+))?"
    r"(?:\+([\w.]+))?$"
)


@dataclass(order=True)
class SemVer:
    """Semantic version with comparison support."""

    major: int = 0
    minor: int = 0
    patch: int = 0
    pre: str = ""

    @classmethod
    def parse(cls, version: str) -> SemVer:
        m = _SEMVER_RE.match(version.strip())
        if not m:
            raise ValueError(f"Invalid semver: {version}")
        return cls(
            major=int(m.group(1)),
            minor=int(m.group(2)),
            patch=int(m.group(3)),
            pre=m.group(4) or "",
        )

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.pre:
            base += f"-{self.pre}"
        return base


# ── Data classes ─────────────────────────────────────────────

@dataclass
class UpdateInfo:
    """Результат перевірки оновлень."""

    current_version: str
    latest_version: str
    update_available: bool
    changelog_url: str = ""
    release_date: str = ""


@dataclass
class UpdateCheckState:
    """Стан останньої перевірки, зберігається в JSON."""

    last_check_ts: float = 0.0
    last_version_seen: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_check_ts": self.last_check_ts,
            "last_version_seen": self.last_version_seen,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UpdateCheckState:
        return cls(
            last_check_ts=data.get("last_check_ts", 0.0),
            last_version_seen=data.get(
                "last_version_seen", ""
            ),
        )


# ── AutoUpdater ──────────────────────────────────────────────

class AutoUpdater:
    """Перевірка та встановлення оновлень Posipaka.

    Ніколи не застосовує оновлення автоматично —
    потрібне підтвердження користувача.
    """

    STATE_FILE = "update_check.json"
    BACKUP_DIR = "backup_before_update"

    def __init__(
        self,
        current_version: str = "0.1.0",
        check_interval_hours: int = 24,
        github_repo: str = "user/posipaka",
        data_dir: Path | None = None,
        base_url: str = "https://api.github.com",
        audit_logger: Any = None,
    ) -> None:
        self.current_version = current_version
        self.check_interval_hours = check_interval_hours
        self.github_repo = github_repo
        self.data_dir = data_dir or (
            Path.home() / ".posipaka"
        )
        self.base_url = base_url.rstrip("/")
        self._audit = audit_logger
        self._state = self._load_state()

    # ── State persistence ────────────────────────────────

    @property
    def _state_path(self) -> Path:
        return self.data_dir / self.STATE_FILE

    def _load_state(self) -> UpdateCheckState:
        if self._state_path.exists():
            try:
                data = json.loads(
                    self._state_path.read_text("utf-8")
                )
                return UpdateCheckState.from_dict(data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    f"Cannot load update state: {e}"
                )
        return UpdateCheckState()

    def _save_state(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(self._state.to_dict(), indent=2),
            encoding="utf-8",
        )

    @property
    def _last_check(self) -> float:
        return self._state.last_check_ts

    # ── Should check ─────────────────────────────────────

    def should_check(self) -> bool:
        """True якщо пройшло достатньо часу з останньої перевірки."""
        if self._state.last_check_ts == 0.0:
            return True
        elapsed_hours = (
            (time.time() - self._state.last_check_ts) / 3600
        )
        return elapsed_hours >= self.check_interval_hours

    # ── Check for updates ────────────────────────────────

    async def check_for_updates(self) -> UpdateInfo:
        """Перевірити наявність оновлень через GitHub Releases."""
        if httpx is None:
            logger.warning("httpx not installed — skip update check")
            return UpdateInfo(
                current_version=self.current_version,
                latest_version=self.current_version,
                update_available=False,
            )

        url = (
            f"{self.base_url}/repos/{self.github_repo}"
            f"/releases/latest"
        )
        self._audit_log(
            "update_check_start",
            {"url": url},
        )

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
            ) as client:
                resp = await client.get(
                    url,
                    headers={"Accept": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error(f"Update check failed: {e}")
            self._audit_log(
                "update_check_error",
                {"error": str(e)},
            )
            return UpdateInfo(
                current_version=self.current_version,
                latest_version=self.current_version,
                update_available=False,
            )

        tag = data.get("tag_name", "")
        published = data.get("published_at", "")
        html_url = data.get("html_url", "")

        try:
            latest = SemVer.parse(tag)
            current = SemVer.parse(self.current_version)
            available = latest > current
        except ValueError:
            logger.warning(f"Cannot parse version tag: {tag}")
            available = False

        # Оновити стан
        self._state.last_check_ts = time.time()
        self._state.last_version_seen = tag
        self._save_state()

        info = UpdateInfo(
            current_version=self.current_version,
            latest_version=tag.lstrip("v"),
            update_available=available,
            changelog_url=html_url,
            release_date=published,
        )

        self._audit_log(
            "update_check_done",
            {
                "current": self.current_version,
                "latest": info.latest_version,
                "available": available,
            },
        )
        return info

    # ── Download update ──────────────────────────────────

    async def download_update(self, version: str) -> str:
        """Завантажити пакет через pip download.

        Returns:
            Шлях до завантаженого файлу або повідомлення.
        """
        download_dir = self.data_dir / "downloads"
        download_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "pip", "download",
            f"posipaka=={version}",
            "-d", str(download_dir),
            "--no-deps",
        ]

        self._audit_log(
            "update_download_start",
            {"version": version},
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")
            logger.error(
                f"pip download failed (rc={proc.returncode}): "
                f"{err[:200]}"
            )
            self._audit_log(
                "update_download_error",
                {
                    "version": version,
                    "returncode": proc.returncode,
                    "stderr": err[:500],
                },
            )
            return f"Download failed: {err[:200]}"

        msg = stdout.decode("utf-8", errors="replace")
        self._audit_log(
            "update_download_done",
            {"version": version, "dir": str(download_dir)},
        )
        logger.info(f"Downloaded posipaka=={version}")
        return f"Downloaded to {download_dir}: {msg[:200]}"

    # ── Backup before update ─────────────────────────────

    def _create_backup(self) -> Path:
        """Створити бекап data_dir перед оновленням."""
        backup_path = (
            self.data_dir
            / self.BACKUP_DIR
            / f"backup_{int(time.time())}"
        )
        backup_path.mkdir(parents=True, exist_ok=True)

        # Копіюємо критичні файли
        critical = [
            "SOUL.md", "USER.md", "MEMORY.md",
            "config.yaml", "memory.db",
        ]
        for name in critical:
            src = self.data_dir / name
            if src.exists():
                shutil.copy2(src, backup_path / name)

        logger.info(f"Backup created: {backup_path}")
        self._audit_log(
            "update_backup_created",
            {"path": str(backup_path)},
        )
        return backup_path

    # ── Apply update ─────────────────────────────────────

    async def apply_update(self) -> str:
        """Встановити оновлення через pip install --upgrade.

        ВАЖЛИВО: викликати тільки після підтвердження
        користувача.

        Returns:
            Результат встановлення.
        """
        # 1. Бекап
        backup_path = self._create_backup()

        self._audit_log(
            "update_apply_start",
            {"backup": str(backup_path)},
        )

        # 2. pip install --upgrade
        cmd = [
            "pip", "install", "--upgrade", "posipaka",
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")
            logger.error(
                f"pip install --upgrade failed "
                f"(rc={proc.returncode}): {err[:200]}"
            )
            self._audit_log(
                "update_apply_error",
                {
                    "returncode": proc.returncode,
                    "stderr": err[:500],
                    "backup": str(backup_path),
                },
            )
            return (
                f"Update failed (rc={proc.returncode}). "
                f"Backup at {backup_path}.\n"
                f"Error: {err[:300]}"
            )

        out = stdout.decode("utf-8", errors="replace")
        logger.info("Update applied successfully")
        self._audit_log(
            "update_apply_done",
            {"stdout": out[:500], "backup": str(backup_path)},
        )
        return (
            f"Update applied successfully. "
            f"Backup at {backup_path}.\n"
            f"Restart the application to use the new version."
        )

    # ── Changelog ────────────────────────────────────────

    async def get_changelog(self, version: str) -> str:
        """Отримати release notes для конкретної версії."""
        if httpx is None:
            return "httpx not installed — cannot fetch changelog"

        url = (
            f"{self.base_url}/repos/{self.github_repo}"
            f"/releases/tags/v{version.lstrip('v')}"
        )

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
            ) as client:
                resp = await client.get(
                    url,
                    headers={"Accept": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error(f"Cannot fetch changelog: {e}")
            return f"Cannot fetch changelog: {e}"

        body = data.get("body", "No release notes.")
        name = data.get("name", version)
        return f"## {name}\n\n{body}"

    # ── CLI formatting ───────────────────────────────────

    def format_update_message(
        self, info: UpdateInfo,
    ) -> str:
        """Форматування повідомлення для CLI/месенджера."""
        if not info.update_available:
            return (
                f"Posipaka v{info.current_version} "
                f"is up to date."
            )

        lines = [
            "Update available!",
            "-" * 40,
            f"  Current: v{info.current_version}",
            f"  Latest:  v{info.latest_version}",
        ]

        if info.release_date:
            lines.append(f"  Released: {info.release_date}")

        if info.changelog_url:
            lines.append(f"  Details: {info.changelog_url}")

        lines.append("-" * 40)
        lines.append(
            "Run 'posipaka update' to install."
        )
        return "\n".join(lines)

    # ── Audit helper ─────────────────────────────────────

    def _audit_log(
        self,
        event: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Логувати дію в audit log якщо доступний."""
        if self._audit is not None:
            try:
                self._audit.log(event, data)
            except Exception as e:
                logger.warning(
                    f"Audit log failed for {event}: {e}"
                )
        logger.debug(f"auto_update: {event} {data or {}}")
