"""GDPR/Privacy — data export та видалення (секція 102.13 MASTER.md)."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from loguru import logger


class PrivacyManager:
    """GDPR-like data export та видалення."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    async def export_user_data(self) -> Path:
        """Експорт всіх даних у ZIP."""
        export_dir = self._data_dir / "export"
        export_dir.mkdir(exist_ok=True)
        archive = export_dir / "posipaka_my_data.zip"

        with zipfile.ZipFile(str(archive), "w", zipfile.ZIP_DEFLATED) as zf:
            # SQLite → JSON
            db_path = self._data_dir / "memory.db"
            if db_path.exists():
                try:

                    # Sync fallback for export
                    import sqlite3

                    conn = sqlite3.connect(str(db_path))
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute(
                        "SELECT session_id, role, content, created_at "
                        "FROM messages ORDER BY created_at"
                    )
                    rows = cursor.fetchall()
                    messages = [
                        {
                            "session": r["session_id"],
                            "role": r["role"],
                            "content": r["content"],
                            "time": r["created_at"],
                        }
                        for r in rows
                    ]
                    conn.close()
                    zf.writestr(
                        "messages.json",
                        json.dumps(messages, indent=2, ensure_ascii=False),
                    )
                except Exception as e:
                    logger.warning(f"Export messages error: {e}")

            # Файли
            for name in ("MEMORY.md", "USER.md", "SOUL.md", "config.yaml"):
                path = self._data_dir / name
                if path.exists():
                    zf.write(str(path), name)

            # Audit
            for name in ("audit.log", "audit.jsonl"):
                path = self._data_dir / name
                if path.exists():
                    zf.write(str(path), name)

        logger.info(f"Data export: {archive}")
        return archive

    async def delete_all_data(self, confirm: bool = False) -> bool:
        """Видалити ВСІ дані. Потребує confirm=True."""
        if not confirm:
            return False

        files = [
            "memory.db",
            "MEMORY.md",
            "USER.md",
            "audit.log",
            "audit.jsonl",
        ]
        dirs = ["chroma", "tantivy_index", "logs"]

        for f in files:
            path = self._data_dir / f
            if path.exists():
                path.unlink()

        for d in dirs:
            path = self._data_dir / d
            if path.exists():
                shutil.rmtree(path)

        logger.info("All user data deleted (GDPR)")
        return True
