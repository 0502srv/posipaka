"""I18nTranslator — переклади з fallback chain."""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

LOCALE_DIR = Path(__file__).parent / "locale"

_translators: dict[str, I18nTranslator] = {}
_missing_keys: dict[str, set[str]] = {}


class I18nTranslator:
    """
    Fallback chain: запитана мова → 'en' → 'uk'.
    Missing keys логуються для coverage tracking.
    Lazy load — файли завантажуються при першому запиті.
    """

    def __init__(self, lang: str) -> None:
        self.lang = lang
        self._messages: dict[str, dict] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        # Load requested language
        self._messages = self._load_lang(self.lang)

        # Load fallbacks
        if self.lang != "en":
            en = self._load_lang("en")
            self._merge_fallback(en)
        if self.lang != "uk":
            uk = self._load_lang("uk")
            self._merge_fallback(uk)

    def _load_lang(self, lang: str) -> dict:
        """Завантажити всі JSON файли для мови."""
        lang_dir = LOCALE_DIR / lang
        if not lang_dir.exists():
            return {}
        messages = {}
        for f in lang_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data.pop("_meta", None)
                messages.update(data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"i18n load error {f}: {e}")
        return messages

    def _merge_fallback(self, fallback: dict) -> None:
        """Заповнити відсутні ключі з fallback."""
        for key, value in fallback.items():
            if key not in self._messages:
                self._messages[key] = value
            elif isinstance(value, dict) and isinstance(
                self._messages[key], dict
            ):
                for k, v in value.items():
                    if k not in self._messages[key]:
                        self._messages[key][k] = v

    def __call__(self, key: str, **kwargs: str) -> str:
        """t("errors.injection_blocked", budget="$5")."""
        self._load()

        parts = key.split(".", 1)
        if len(parts) == 2:
            section, subkey = parts
            section_data = self._messages.get(section, {})
            if isinstance(section_data, dict):
                text = section_data.get(subkey)
                if text:
                    return self._format(text, kwargs)

        # Direct key lookup
        text = self._messages.get(key)
        if text and isinstance(text, str):
            return self._format(text, kwargs)

        # Missing key
        _missing_keys.setdefault(self.lang, set()).add(key)
        logger.debug(f"i18n missing: [{self.lang}] {key}")
        return key

    @staticmethod
    def _format(text: str, kwargs: dict) -> str:
        if not kwargs:
            return text
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text


def get_translator(lang: str = "uk") -> I18nTranslator:
    """Отримати або створити translator для мови."""
    if lang not in _translators:
        _translators[lang] = I18nTranslator(lang)
    return _translators[lang]


def get_missing_keys() -> dict[str, set[str]]:
    """Coverage report — ключі без перекладу."""
    return dict(_missing_keys)
