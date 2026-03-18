"""Runtime config — JSON конфіг що переживає рестарти Docker.

Зберігається в ~/.posipaka/config.json (Docker volume).
Має пріоритет над .env для налаштувань що змінюються через Web UI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

_DEFAULT_PATH = Path.home() / ".posipaka" / "config.json"


class RuntimeConfig:
    """Read/write JSON конфіг в Docker volume."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DEFAULT_PATH
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(
                    self._path.read_text(encoding="utf-8"),
                )
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Cannot load runtime config: {e}")
                self._data = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Get value by dot-separated key: 'llm.provider'."""
        parts = key.split(".")
        obj = self._data
        for part in parts:
            if isinstance(obj, dict) and part in obj:
                obj = obj[part]
            else:
                return default
        return obj

    def set(self, key: str, value: Any) -> None:
        """Set value by dot-separated key and save."""
        parts = key.split(".")
        obj = self._data
        for part in parts[:-1]:
            if part not in obj or not isinstance(obj[part], dict):
                obj[part] = {}
            obj = obj[part]
        obj[parts[-1]] = value
        self._save()

    def set_many(self, updates: dict[str, Any]) -> None:
        """Set multiple values and save once."""
        for key, value in updates.items():
            parts = key.split(".")
            obj = self._data
            for part in parts[:-1]:
                if part not in obj or not isinstance(obj[part], dict):
                    obj[part] = {}
                obj = obj[part]
            obj[parts[-1]] = value
        self._save()

    def get_section(self, section: str) -> dict[str, Any]:
        """Get entire section as dict."""
        return dict(self._data.get(section, {}))

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def apply_to_settings(self, settings: Any) -> None:
        """Override Settings fields from runtime config.

        Called at startup AFTER env vars are loaded.
        Runtime config has highest priority.
        """
        rc = self._data

        # LLM
        llm = rc.get("llm", {})
        if llm.get("provider"):
            settings.llm.provider = llm["provider"]
        if llm.get("model"):
            settings.llm.model = llm["model"]
        if llm.get("api_key"):
            from pydantic import SecretStr

            settings.llm.api_key = SecretStr(llm["api_key"])
        if llm.get("temperature") is not None:
            settings.llm.temperature = float(llm["temperature"])
        if llm.get("max_tokens"):
            settings.llm.max_tokens = int(llm["max_tokens"])
        if llm.get("fallback_provider"):
            settings.llm.fallback_provider = llm["fallback_provider"]
        if llm.get("fallback_model"):
            settings.llm.fallback_model = llm["fallback_model"]
        if llm.get("fallback_api_key"):
            from pydantic import SecretStr

            settings.llm.fallback_api_key = SecretStr(
                llm["fallback_api_key"],
            )

        # Soul
        soul = rc.get("soul", {})
        if soul.get("name"):
            settings.soul.name = soul["name"]
        if soul.get("language"):
            settings.soul.language = soul["language"]
        if soul.get("timezone"):
            settings.soul.timezone = soul["timezone"]

        # Cost
        cost = rc.get("cost", {})
        if cost.get("daily_budget_usd") is not None:
            settings.cost.daily_budget_usd = float(
                cost["daily_budget_usd"],
            )
        if cost.get("per_request_max_usd") is not None:
            settings.cost.per_request_max_usd = float(
                cost["per_request_max_usd"],
            )
        if cost.get("per_session_max_usd") is not None:
            settings.cost.per_session_max_usd = float(
                cost["per_session_max_usd"],
            )

        # Channels
        channels = rc.get("enabled_channels")
        if channels:
            settings.enabled_channels = channels

        # Telegram
        tg = rc.get("telegram", {})
        if tg.get("token"):
            from pydantic import SecretStr

            settings.telegram.token = SecretStr(tg["token"])

        logger.debug("Runtime config applied to settings")
