"""Language Detector (секція 50.6 MASTER.md)."""

from __future__ import annotations


class LanguageDetector:
    """
    Визначення мови: explicit → config → auto-detect → 'uk'.
    """

    # Tier 1 + 2 languages
    LANGUAGE_NAMES: dict[str, str] = {
        "uk": "Українська",
        "en": "English",
        "de": "Deutsch",
        "fr": "Français",
        "es": "Español",
        "pl": "Polski",
        "it": "Italiano",
        "pt": "Português",
        "nl": "Nederlands",
        "cs": "Čeština",
        "ro": "Română",
        "hu": "Magyar",
        "sk": "Slovenčina",
        "bg": "Български",
        "zh": "中文",
        "ja": "日本語",
        "ko": "한국어",
        "ar": "العربية",
        "tr": "Türkçe",
        "ru": "Русский",
    }

    def __init__(self, default_lang: str = "uk") -> None:
        self._default = default_lang
        self._user_langs: dict[str, str] = {}  # user_id → lang

    def detect(self, text: str, user_id: str | None = None) -> str:
        """
        Визначити мову.

        Priority: user explicit setting → auto-detect → default.
        """
        # 1. Explicit user setting
        if user_id and user_id in self._user_langs:
            return self._user_langs[user_id]

        # 2. Auto-detect
        detected = self._auto_detect(text)
        if detected:
            return detected

        return self._default

    def set_user_language(self, user_id: str, lang: str) -> None:
        """Явно встановити мову для користувача."""
        self._user_langs[user_id] = lang

    @staticmethod
    def _auto_detect(text: str) -> str | None:
        """Автоматичне визначення мови (спрощене, без зовнішніх бібліотек)."""
        if not text or len(text) < 3:
            return None

        lower = text.lower()

        # Ukrainian specific
        uk_chars = set("іїєґ")
        if any(c in lower for c in uk_chars):
            return "uk"

        # Russian specific (not in Ukrainian)
        ru_chars = set("ыэъё")
        if any(c in lower for c in ru_chars):
            return "ru"

        # Bulgarian
        if any(c in lower for c in "ъь") and "щ" in lower:
            return "bg"

        # Chinese
        if any("\u4e00" <= c <= "\u9fff" for c in lower):
            return "zh"

        # Japanese (Hiragana/Katakana)
        if any("\u3040" <= c <= "\u30ff" for c in lower):
            return "ja"

        # Korean
        if any("\uac00" <= c <= "\ud7af" for c in lower):
            return "ko"

        # Arabic
        if any("\u0600" <= c <= "\u06ff" for c in lower):
            return "ar"

        # Hebrew
        if any("\u0590" <= c <= "\u05ff" for c in lower):
            return "he"

        # Cyrillic fallback
        if any("\u0400" <= c <= "\u04ff" for c in lower):
            return "uk"

        # Latin-based — check for specific markers
        # German
        if any(c in lower for c in "äöüß"):
            return "de"

        # French
        if any(c in lower for c in "éèêëàâùûçœæ"):
            return "fr"

        # Spanish
        if "¿" in lower or "¡" in lower or "ñ" in lower:
            return "es"

        # Polish
        if any(c in lower for c in "ąćęłńóśźż"):
            return "pl"

        # Turkish
        if any(c in lower for c in "ğışçö"):
            return "tr"

        # Default to English for Latin text
        if any("a" <= c <= "z" for c in lower):
            return "en"

        return None
