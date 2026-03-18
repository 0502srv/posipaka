"""Backup & Restore система для ~/.posipaka."""

from __future__ import annotations

import tarfile
from datetime import datetime
from pathlib import Path

from loguru import logger


class BackupManager:
    """Створення та відновлення бекапів data_dir."""

    BACKUP_EXTENSIONS = {".db", ".md", ".yaml", ".yml", ".log", ".json", ".enc"}
    EXCLUDE_DIRS = {"chroma", "__pycache__", ".venv"}

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._backup_dir = data_dir / "backups"

    def create_backup(self, name: str | None = None) -> Path:
        """Створити backup у tar.gz."""
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        if name is None:
            name = datetime.now().strftime("backup_%Y%m%d_%H%M%S")

        backup_path = self._backup_dir / f"{name}.tar.gz"

        with tarfile.open(str(backup_path), "w:gz") as tar:
            for item in self._data_dir.rglob("*"):
                if item.is_file() and not self._should_exclude(item):
                    arcname = item.relative_to(self._data_dir)
                    tar.add(str(item), arcname=str(arcname))

        size_mb = backup_path.stat().st_size / (1024 * 1024)
        logger.info(f"Backup created: {backup_path} ({size_mb:.1f} MB)")
        return backup_path

    def restore_backup(self, backup_path: Path) -> None:
        """Відновити з backup."""
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")

        with tarfile.open(str(backup_path), "r:gz") as tar:
            # Security: check for path traversal in archive
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name:
                    raise ValueError(f"Небезпечний шлях в архіві: {member.name}")

            # Python 3.12+: filter='data' для безпечного extract
            import sys

            if sys.version_info >= (3, 12):
                tar.extractall(path=str(self._data_dir), filter="data")
            else:
                # Python 3.11: ручна валідація (CVE-2007-4559)
                for member in tar.getmembers():
                    member_path = (self._data_dir / member.name).resolve()
                    if not str(member_path).startswith(str(self._data_dir.resolve())):
                        raise ValueError(f"Path traversal: {member.name} resolves outside data_dir")
                    if member.issym() or member.islnk():
                        raise ValueError(f"Symlink/hardlink blocked: {member.name}")
                    if member.mode & 0o7000:
                        member.mode = member.mode & 0o0777
                tar.extractall(path=str(self._data_dir))  # noqa: S202

        logger.info(f"Restored from: {backup_path}")

    def list_backups(self) -> list[dict]:
        """Список доступних бекапів."""
        if not self._backup_dir.exists():
            return []

        backups = []
        for f in sorted(self._backup_dir.glob("*.tar.gz"), reverse=True):
            backups.append(
                {
                    "name": f.stem.replace(".tar", ""),
                    "path": str(f),
                    "size_mb": f.stat().st_size / (1024 * 1024),
                    "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                }
            )
        return backups

    def cleanup_old_backups(self, keep: int = 5) -> int:
        """Видалити старі бекапи, залишити keep останніх."""
        backups = self.list_backups()
        removed = 0
        for backup in backups[keep:]:
            Path(backup["path"]).unlink()
            removed += 1
        if removed:
            logger.info(f"Cleaned up {removed} old backups")
        return removed

    def _should_exclude(self, path: Path) -> bool:
        """Чи виключати файл з бекапу."""
        parts = path.relative_to(self._data_dir).parts
        if any(part in self.EXCLUDE_DIRS for part in parts):
            return True
        return "backups" in parts
