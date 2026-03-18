"""GDPR-compliant privacy manager — експорт, видалення, retention policies."""

from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger


class PrivacyManager:
    """
    GDPR-compliant керування приватністю даних.

    Можливості:
    - Експорт даних (всі дані користувача як ZIP)
    - Видалення даних (повне стирання)
    - Retention policy (автоочищення старих даних)
    - Відстеження згоди (consent tracking)
    - EU AI Act disclosure
    """

    EU_AI_ACT_DISCLOSURE = (
        "Цей агент використовує штучний інтелект (Large Language Model) "
        "для обробки ваших повідомлень. Ваші дані зберігаються локально "
        "на вашому сервері. Ви маєте право на експорт (/export) та "
        "видалення (/delete_data) усіх своїх даних у будь-який час."
    )

    DEFAULT_RETENTION_DAYS: dict[str, int] = {
        "messages": 365,
        "audit_log": 730,  # 2 роки для compliance
        "memory_facts": 0,  # 0 = зберігати назавжди
        "logs": 90,
        "backups": 30,
    }

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._consent_file = data_dir / ".privacy_consent.json"

    async def export_user_data(self) -> Path:
        """
        Експорт всіх даних користувача у ZIP архів.
        GDPR Article 20: Right to data portability.
        """
        export_dir = self._data_dir / "export"
        export_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = export_dir / f"posipaka_export_{ts}.zip"

        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Профіль користувача
            for md_file in ("USER.md", "MEMORY.md", "SOUL.md"):
                path = self._data_dir / md_file
                if path.exists():
                    zf.write(path, md_file)

            # Розмови з SQLite
            db_path = self._data_dir / "memory.db"
            if db_path.exists():
                try:
                    import aiosqlite

                    async with aiosqlite.connect(str(db_path)) as db:
                        # Messages
                        cursor = await db.execute(
                            "SELECT * FROM messages ORDER BY created_at"
                        )
                        cols = [d[0] for d in cursor.description] if cursor.description else []
                        rows = await cursor.fetchall()
                        messages = [dict(zip(cols, row)) for row in rows]

                        # Facts
                        try:
                            cursor = await db.execute(
                                "SELECT * FROM facts ORDER BY created_at"
                            )
                            cols = [d[0] for d in cursor.description] if cursor.description else []
                            rows = await cursor.fetchall()
                            facts = [dict(zip(cols, row)) for row in rows]
                        except Exception:
                            facts = []

                    zf.writestr(
                        "messages.json",
                        json.dumps(messages, indent=2, ensure_ascii=False, default=str),
                    )
                    if facts:
                        zf.writestr(
                            "facts.json",
                            json.dumps(facts, indent=2, ensure_ascii=False, default=str),
                        )
                except Exception as e:
                    logger.error(f"Помилка експорту БД: {e}")

            # Audit log
            for name in ("audit.log", "audit.jsonl"):
                audit = self._data_dir / name
                if audit.exists():
                    zf.write(audit, name)

            # Конфіг (без секретів)
            config = self._data_dir / "config.yaml"
            if config.exists():
                zf.write(config, "config.yaml")

            # Privacy consent
            if self._consent_file.exists():
                zf.write(self._consent_file, "privacy_consent.json")

        logger.info(f"Експорт даних створено: {archive_path} ({archive_path.stat().st_size} bytes)")
        return archive_path

    async def delete_all_user_data(self, confirm: bool = False) -> dict:
        """
        Видалити ВСІ дані користувача. GDPR Article 17: Right to erasure.
        Потребує явного підтвердження.
        Повертає звіт про видалення.
        """
        if not confirm:
            return {"error": "Потрібне підтвердження. Передайте confirm=True."}

        report: dict[str, list] = {"deleted_files": [], "deleted_dirs": [], "errors": []}

        files_to_delete = [
            "memory.db", "MEMORY.md", "USER.md",
            "audit.jsonl", "audit.log",
            ".secrets_rotation.json", ".privacy_consent.json",
        ]
        dirs_to_delete = [
            "chroma", "tantivy_index", "logs", "export",
        ]

        for f in files_to_delete:
            path = self._data_dir / f
            if path.exists():
                try:
                    path.unlink()
                    report["deleted_files"].append(f)
                except Exception as e:
                    report["errors"].append(f"{f}: {e}")

        for d in dirs_to_delete:
            path = self._data_dir / d
            if path.exists():
                try:
                    shutil.rmtree(path)
                    report["deleted_dirs"].append(d)
                except Exception as e:
                    report["errors"].append(f"{d}: {e}")

        logger.warning(f"Дані користувача видалено: {report}")
        return report

    async def apply_retention_policy(
        self, custom_days: dict[str, int] | None = None
    ) -> dict:
        """
        Застосувати retention policy. Видалити дані старіші за поріг.
        Призначено для scheduled execution (щоденний cron job).
        """
        retention = {**self.DEFAULT_RETENTION_DAYS, **(custom_days or {})}
        report: dict[str, dict] = {"cleaned": {}}

        # Очистити старі логи
        if retention["logs"] > 0:
            logs_dir = self._data_dir / "logs"
            if logs_dir.exists():
                cutoff = datetime.now() - timedelta(days=retention["logs"])
                count = 0
                for f in logs_dir.iterdir():
                    if f.is_file() and datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                        f.unlink()
                        count += 1
                if count:
                    report["cleaned"]["logs"] = count

        # Очистити старі бекапи
        if retention["backups"] > 0:
            backups_dir = self._data_dir / "backups"
            if backups_dir.exists():
                cutoff = datetime.now() - timedelta(days=retention["backups"])
                count = 0
                for f in backups_dir.iterdir():
                    if f.is_file() and datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                        f.unlink()
                        count += 1
                if count:
                    report["cleaned"]["backups"] = count

        # Очистити старі повідомлення з БД
        if retention["messages"] > 0:
            db_path = self._data_dir / "memory.db"
            if db_path.exists():
                try:
                    import aiosqlite

                    cutoff_str = (
                        datetime.now() - timedelta(days=retention["messages"])
                    ).isoformat()
                    async with aiosqlite.connect(str(db_path)) as db:
                        cursor = await db.execute(
                            "DELETE FROM messages WHERE created_at < ?",
                            (cutoff_str,),
                        )
                        if cursor.rowcount:
                            report["cleaned"]["messages"] = cursor.rowcount
                        await db.commit()
                except Exception as e:
                    logger.error(f"Retention cleanup для messages не вдався: {e}")

        if report["cleaned"]:
            logger.info(f"Retention policy застосовано: {report['cleaned']}")
        return report

    def record_consent(self, user_id: str, consent_type: str, granted: bool) -> None:
        """Записати згоду користувача для відстеження приватності."""
        data: dict = {}
        if self._consent_file.exists():
            data = json.loads(self._consent_file.read_text())

        if user_id not in data:
            data[user_id] = {}

        data[user_id][consent_type] = {
            "granted": granted,
            "timestamp": datetime.now().isoformat(),
        }
        self._consent_file.write_text(json.dumps(data, indent=2))

    def get_first_contact_disclosure(self) -> str:
        """EU AI Act: обов'язкове розкриття при першому контакті."""
        return self.EU_AI_ACT_DISCLOSURE
