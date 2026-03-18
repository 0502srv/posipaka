"""Secrets Rotation Policy — tracking та нагадування."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

ROTATION_SCHEDULE: dict[str, int] = {
    "LLM_API_KEY": 90,
    "ANTHROPIC_API_KEY": 90,
    "OPENAI_API_KEY": 90,
    "TELEGRAM_TOKEN": 180,
    "DISCORD_TOKEN": 180,
    "SLACK_BOT_TOKEN": 90,
    "GOOGLE_TOKEN": 30,
    "WEB_UI_PASSWORD": 90,
}


class SecretsRotationPolicy:
    """Нагадування про ротацію секретів (не автоматична ротація)."""

    def __init__(self, data_dir: Path) -> None:
        self._file = data_dir / ".secrets_rotation.json"

    def check_rotation_needed(self) -> list[dict]:
        """Які секрети потребують ротації."""
        if not self._file.exists():
            return []

        data = json.loads(self._file.read_text(encoding="utf-8"))
        warnings = []
        now = datetime.now(UTC)

        for key_name, max_days in ROTATION_SCHEDULE.items():
            last_rotated = data.get(key_name)
            if not last_rotated:
                continue
            last_date = datetime.fromisoformat(last_rotated)
            if last_date.tzinfo is None:
                last_date = last_date.replace(tzinfo=UTC)
            age_days = (now - last_date).days
            if age_days >= max_days:
                warnings.append(
                    {
                        "key": key_name,
                        "age_days": age_days,
                        "max_days": max_days,
                        "message": (
                            f"{key_name}: {age_days} днів з ротації (рекомендовано: {max_days})"
                        ),
                    }
                )
        return warnings

    def record_rotation(self, key_name: str) -> None:
        """Записати ротацію."""
        data: dict = {}
        if self._file.exists():
            data = json.loads(self._file.read_text(encoding="utf-8"))
        data[key_name] = datetime.now(UTC).isoformat()
        self._file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get_report(self) -> str:
        warnings = self.check_rotation_needed()
        if not warnings:
            return "Всі секрети актуальні."
        lines = ["Потрібна ротація секретів:\n"]
        for w in warnings:
            lines.append(f"  {w['message']}")
        return "\n".join(lines)
