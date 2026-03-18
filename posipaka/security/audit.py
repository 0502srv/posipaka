"""Hash-chained AuditLogger — кожна подія пов'язана з попередньою через SHA-256."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from pathlib import Path
from typing import Any

from loguru import logger


class AuditLogger:
    """
    Hash-chained JSONL audit log.

    Кожен запис містить hash попереднього запису — тампер-детекція.
    """

    GENESIS_HASH = "genesis"

    def __init__(self, log_path: Path) -> None:
        self._path = log_path
        self._prev_hash = self.GENESIS_HASH
        self._load_last_hash()

    def _load_last_hash(self) -> None:
        """Прочитати hash останнього запису (якщо файл існує)."""
        if not self._path.exists() or self._path.stat().st_size == 0:
            return
        try:
            with open(self._path) as f:
                last_line = ""
                for line in f:
                    line = line.strip()
                    if line:
                        last_line = line
                if last_line:
                    record = json.loads(last_line)
                    self._prev_hash = record.get("hash", self.GENESIS_HASH)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not load last audit hash: {e}")

    def log(self, event: str, data: dict[str, Any] | None = None) -> dict:
        """Записати подію в audit log з hash chain."""
        record = {
            "ts": time.time(),
            "event": event,
            "data": self._sanitize_data(data or {}),
            "prev_hash": self._prev_hash,
        }
        record_json = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        record["hash"] = hashlib.sha256(record_json.encode()).hexdigest()
        self._prev_hash = record["hash"]

        with open(self._path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return record

    def verify_integrity(self) -> tuple[bool, int, str]:
        """
        Перевірити цілісність всього audit log.

        Returns:
            (is_valid, total_entries, message)
        """
        if not self._path.exists():
            return True, 0, "Audit log порожній"

        prev_hash = self.GENESIS_HASH
        count = 0

        with open(self._path) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    return False, count, f"Невалідний JSON на рядку {line_num}"

                if record.get("prev_hash") != prev_hash:
                    return (
                        False,
                        count,
                        (
                            f"Порушення ланцюга на рядку {line_num}: "
                            f"очікувався prev_hash={prev_hash[:16]}..."
                        ),
                    )

                stored_hash = record.pop("hash")
                record_json = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                computed_hash = hashlib.sha256(record_json.encode()).hexdigest()

                if stored_hash != computed_hash:
                    return False, count, (f"Тампер на рядку {line_num}: hash не збігається")

                prev_hash = stored_hash
                count += 1

        return True, count, f"Audit log цілісний ({count} записів)"

    def export_csv(self) -> str:
        """Експортувати audit log в CSV формат."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["timestamp", "event", "data", "hash"])

        if self._path.exists():
            with open(self._path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    writer.writerow(
                        [
                            record.get("ts", ""),
                            record.get("event", ""),
                            json.dumps(record.get("data", {})),
                            record.get("hash", "")[:16] + "...",
                        ]
                    )

        return output.getvalue()

    @staticmethod
    def _sanitize_data(data: dict[str, Any]) -> dict[str, Any]:
        """Обрізати чутливі дані перед записом."""
        sanitized = {}
        for key, value in data.items():
            if isinstance(value, str):
                if key in ("content", "text", "body", "message"):
                    sanitized[key] = value[:50] + ("..." if len(value) > 50 else "")
                elif key in ("api_key", "token", "password", "secret"):
                    sanitized[key] = "***REDACTED***"
                else:
                    sanitized[key] = value
            else:
                sanitized[key] = value
        return sanitized
