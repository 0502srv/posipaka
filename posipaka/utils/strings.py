"""Локалізація — всі системні повідомлення Posipaka."""

from __future__ import annotations

import contextlib

STRINGS: dict[str, dict[str, str]] = {
    # ─── Загальні ────────────────────────────────────────────────────────────
    "welcome": {
        "uk": "Привіт, {name}! Я Posipaka — ваш AI-асистент.",
        "en": "Hello, {name}! I'm Posipaka — your AI assistant.",
        "ru": "Привет, {name}! Я Posipaka — ваш AI-ассистент.",
    },
    "help": {
        "uk": (
            "Команди Posipaka:\n\n"
            "/start — привітання\n/help — ця довідка\n/reset — скинути сесію\n"
            "/status — статус агента\n/memory — що я про вас знаю\n"
            "/skills — список навичок\n/cost — витрати за сьогодні\n\n"
            "Просто надішліть повідомлення — і я відповім!"
        ),
        "en": (
            "Posipaka commands:\n\n"
            "/start — greeting\n/help — this help\n/reset — reset session\n"
            "/status — agent status\n/memory — what I know about you\n"
            "/skills — available skills\n/cost — today's costs\n\n"
            "Just send a message — and I'll respond!"
        ),
        "ru": (
            "Команды Posipaka:\n\n"
            "/start — приветствие\n/help — эта справка\n/reset — сбросить сессию\n"
            "/status — статус агента\n/memory — что я о вас знаю\n"
            "/skills — список навыков\n/cost — расходы за сегодня\n\n"
            "Просто отправьте сообщение — и я отвечу!"
        ),
    },
    # ─── Безпека ─────────────────────────────────────────────────────────────
    "injection_blocked": {
        "uk": "Виявлено потенційно небезпечний вміст у повідомленні. Запит відхилено з міркувань безпеки.",  # noqa: E501
        "en": "Potentially dangerous content detected. Request rejected for security reasons.",
        "ru": "Обнаружено потенциально опасное содержимое. Запрос отклонён из соображений безопасности.",  # noqa: E501
    },
    "input_too_long": {
        "uk": "Повідомлення занадто довге: {length} символів (максимум {max}). Спробуйте коротше.",
        "en": "Message too long: {length} chars (max {max}). Try shorter.",
        "ru": "Сообщение слишком длинное: {length} символов (максимум {max}). Попробуйте короче.",
    },
    "unauthorized": {
        "uk": "Вибачте, у вас немає доступу до цього бота.",
        "en": "Sorry, you don't have access to this bot.",
        "ru": "Извините, у вас нет доступа к этому боту.",
    },
    "rate_limited": {
        "uk": "Занадто багато запитів. Зачекайте {seconds:.0f} секунд.",
        "en": "Too many requests. Wait {seconds:.0f} seconds.",
        "ru": "Слишком много запросов. Подождите {seconds:.0f} секунд.",
    },
    # ─── Approval ────────────────────────────────────────────────────────────
    "approval_request": {
        "uk": "Потрібне підтвердження:\n{description}\n\nВідповідайте 'так' або 'ні'",
        "en": "Approval required:\n{description}\n\nReply 'yes' or 'no'",
        "ru": "Требуется подтверждение:\n{description}\n\nОтветьте 'да' или 'нет'",
    },
    "approval_granted": {
        "uk": "Виконано: {result}",
        "en": "Done: {result}",
        "ru": "Выполнено: {result}",
    },
    "approval_denied": {
        "uk": "Дію скасовано.",
        "en": "Action cancelled.",
        "ru": "Действие отменено.",
    },
    "approval_timeout": {
        "uk": "Час підтвердження вичерпано. Дія скасована.",
        "en": "Approval timeout. Action cancelled.",
        "ru": "Время подтверждения истекло. Действие отменено.",
    },
    # ─── Помилки ─────────────────────────────────────────────────────────────
    "llm_unavailable": {
        "uk": "AI-модель тимчасово недоступна. Спробуйте пізніше.",
        "en": "AI model temporarily unavailable. Try again later.",
        "ru": "AI-модель временно недоступна. Попробуйте позже.",
    },
    "llm_fallback": {
        "uk": "Основна AI-модель тимчасово недоступна. Переключаюсь на резервну.",
        "en": "Primary AI model unavailable. Switching to fallback.",
        "ru": "Основная AI-модель недоступна. Переключаюсь на резервную.",
    },
    "budget_exhausted": {
        "uk": "Денний бюджет вичерпано: витрачено ${spent:.2f} з ${limit:.2f}.",
        "en": "Daily budget exhausted: spent ${spent:.2f} of ${limit:.2f}.",
        "ru": "Дневной бюджет исчерпан: потрачено ${spent:.2f} из ${limit:.2f}.",
    },
    "max_iterations": {
        "uk": "Досягнуто максимальну кількість ітерацій. Спробуйте спростити запит.",
        "en": "Maximum iterations reached. Try simplifying your request.",
        "ru": "Достигнуто максимальное количество итераций. Попробуйте упростить запрос.",
    },
    "general_error": {
        "uk": "Виникла помилка. Спробуйте ще раз.",
        "en": "An error occurred. Please try again.",
        "ru": "Произошла ошибка. Попробуйте ещё раз.",
    },
    # ─── Сесія ───────────────────────────────────────────────────────────────
    "session_reset": {
        "uk": "Сесію скинуто.",
        "en": "Session reset.",
        "ru": "Сессия сброшена.",
    },
    "memory_empty": {
        "uk": "Пам'ять порожня.",
        "en": "Memory is empty.",
        "ru": "Память пуста.",
    },
    "no_tools": {
        "uk": "Немає зареєстрованих інструментів.",
        "en": "No registered tools.",
        "ru": "Нет зарегистрированных инструментов.",
    },
}

# Default language
_current_lang = "uk"


def set_language(lang: str) -> None:
    """Встановити мову системних повідомлень."""
    global _current_lang
    if lang in ("uk", "en", "ru"):
        _current_lang = lang


def get_language() -> str:
    return _current_lang


def t(key: str, lang: str | None = None, **kwargs) -> str:
    """Отримати локалізований рядок."""
    lang = lang or _current_lang
    entry = STRINGS.get(key, {})
    text = entry.get(lang) or entry.get("uk") or entry.get("en") or key
    if kwargs:
        with contextlib.suppress(KeyError, IndexError):
            text = text.format(**kwargs)
    return text


def detect_language(text: str) -> str:
    """Автоматичне визначення мови тексту (спрощене)."""
    # Ukrainian specific chars
    uk_chars = set("іїєґ")
    # Russian specific chars (not in Ukrainian)
    ru_chars = set("ыэъ")

    lower = text.lower()
    if any(c in lower for c in uk_chars):
        return "uk"
    if any(c in lower for c in ru_chars):
        return "ru"
    # Check for Cyrillic at all
    if any("\u0400" <= c <= "\u04ff" for c in lower):
        return "uk"  # Default Cyrillic to Ukrainian
    return "en"
