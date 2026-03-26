"""UserProfileLearner — auto-learn user preferences from conversations."""

from __future__ import annotations

import re
import time
from pathlib import Path

from loguru import logger


class UserProfileLearner:
    """Автоматично вивчає преференції користувача і оновлює USER.md.

    Аналізує повідомлення на наявність інформації про юзера:
    - Ім'я, мова, часовий пояс
    - Переваги у відповідях
    - Теми що цікавлять
    - Інструменти що часто використовує
    """

    # Мінімальний інтервал між оновленнями USER.md (5 хвилин)
    UPDATE_INTERVAL = 300

    # Паттерни для витягування інформації
    _NAME_PATTERNS = [
        re.compile(
            r"(?:мене звати|я\s+—?\s*|my name is|i'?m)\s+"
            r"([А-ЯA-Z][а-яa-zА-ЯA-Zіїєґ]+)",
            re.I,
        ),
    ]
    _LANG_INDICATORS = {
        "uk": re.compile(r"[іїєґ]", re.I),
        "ru": re.compile(r"[ыэъё]", re.I),
        "en": re.compile(r"\b(the|is|are|was|been|have|with)\b", re.I),
    }

    def __init__(self, user_md_path: Path) -> None:
        self._path = user_md_path
        self._last_update = 0.0
        self._detected: dict[str, str] = {}
        self._topics: dict[str, int] = {}
        self._tool_usage: dict[str, int] = {}
        self._message_count = 0
        self._load_existing()

    def _load_existing(self) -> None:
        """Load existing USER.md to avoid overwriting user data."""
        if not self._path.exists():
            return
        content = self._path.read_text(encoding="utf-8")
        # Extract existing name if set
        name_match = re.search(r"Ім'я:\s*(.+)", content)
        if name_match and name_match.group(1).strip() not in ("", "—"):
            self._detected["name"] = name_match.group(1).strip()
        lang_match = re.search(r"Мова:\s*(.+)", content)
        if lang_match and lang_match.group(1).strip() not in ("", "—"):
            self._detected["language"] = lang_match.group(1).strip()

    def observe_message(self, text: str, role: str = "user") -> None:
        """Аналізувати повідомлення для витягування інформації."""
        if role != "user":
            return
        self._message_count += 1

        # Detect name
        if "name" not in self._detected:
            for pattern in self._NAME_PATTERNS:
                match = pattern.search(text)
                if match:
                    self._detected["name"] = match.group(1)
                    break

        # Detect language (accumulate evidence)
        for lang, pattern in self._LANG_INDICATORS.items():
            if pattern.search(text):
                key = f"_lang_{lang}"
                self._detected[key] = str(int(self._detected.get(key, "0")) + 1)

    def observe_tool_use(self, tool_name: str) -> None:
        """Track which tools the user triggers."""
        self._tool_usage[tool_name] = self._tool_usage.get(tool_name, 0) + 1

    def maybe_update(self) -> bool:
        """Update USER.md if enough new data collected. Returns True if updated."""
        now = time.time()
        if now - self._last_update < self.UPDATE_INTERVAL:
            return False
        if self._message_count < 5:
            return False

        try:
            self._update_user_md()
            self._last_update = now
            return True
        except Exception as e:
            logger.debug(f"UserProfileLearner update failed: {e}")
            return False

    def _update_user_md(self) -> None:
        """Rewrite USER.md with learned information."""
        # Determine dominant language
        lang_scores = {}
        for lang in ("uk", "ru", "en"):
            key = f"_lang_{lang}"
            lang_scores[lang] = int(self._detected.get(key, "0"))
        dominant_lang = max(lang_scores, key=lang_scores.get) if any(lang_scores.values()) else ""
        lang_names = {"uk": "Українська", "ru": "Русский", "en": "English"}

        name = self._detected.get("name", "")
        language = lang_names.get(dominant_lang, "")

        # Top tools
        top_tools = sorted(self._tool_usage.items(), key=lambda x: -x[1])[:5]
        tools_str = ", ".join(f"{t} ({c}x)" for t, c in top_tools) if top_tools else ""

        # Read existing content to preserve manually set fields
        existing = ""
        if self._path.exists():
            existing = self._path.read_text(encoding="utf-8")

        # Only update if we have new info
        sections = []
        sections.append("# Профіль користувача\n")
        sections.append(f"Ім'я: {name or '—'}")
        sections.append(f"Мова: {language or '—'}")
        if tools_str:
            sections.append(f"Часто використовує: {tools_str}")
        sections.append(f"Повідомлень: {self._message_count}")

        # Preserve any custom content after standard sections
        custom_start = existing.find("\n## ")
        if custom_start > 0:
            sections.append(existing[custom_start:])

        new_content = "\n".join(sections) + "\n"

        # Only write if meaningfully different
        if new_content.strip() != existing.strip():
            self._path.write_text(new_content, encoding="utf-8")
            logger.debug(f"USER.md updated: name={name}, lang={language}")
