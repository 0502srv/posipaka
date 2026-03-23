"""CronParser — natural language → cron job parameters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from posipaka.core.cron_engine import CronType

__all__ = [
    "ParsedSchedule",
    "detect_schedule_intent",
    "format_confirmation",
    "parse_schedule",
]


@dataclass
class ParsedSchedule:
    """Результат парсингу NL-розкладу."""

    cron_type: CronType
    at: str = ""  # ISO datetime
    cron: str = ""  # cron expression
    every: str = ""  # interval
    confidence: float = 0.0
    description: str = ""  # human-readable

    @property
    def is_valid(self) -> bool:
        return self.confidence > 0.5 and bool(self.at or self.cron or self.every)


_RELATIVE_PATTERNS: list[tuple[str, str]] = [
    # "через 30 хвилин", "через 2 години", "через 1 день"
    (r"через\s+(\d+)\s*(хв|хвилин[уи]?|мінут[уи]?|мин)", "minutes"),
    (r"через\s+(\d+)\s*(год|годин[уи]?|час[іов]?|час)", "hours"),
    (r"через\s+(\d+)\s*(дн|дн[іів]|день|дня|дней)", "days"),
    # "in 30 minutes", "in 2 hours"
    (r"in\s+(\d+)\s*min(?:ute)?s?", "minutes"),
    (r"in\s+(\d+)\s*hours?", "hours"),
    (r"in\s+(\d+)\s*days?", "days"),
]

_RECURRING_PATTERNS: list[tuple[str, str]] = [
    # "щодня о 9", "щодня о 9:30"
    (r"щодня\s+о\s+(\d{1,2})(?::(\d{2}))?", "daily"),
    (r"каждый\s+день\s+в\s+(\d{1,2})(?::(\d{2}))?", "daily"),
    (r"every\s+day\s+at\s+(\d{1,2})(?::(\d{2}))?", "daily"),
    (r"daily\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?", "daily"),
    # "кожні 30 хвилин"
    (r"кожн[іи]\s+(\d+)\s*(хв|хвилин|мінут|мин)", "interval_min"),
    (r"кожн[іи]\s+(\d+)\s*(год|годин|час)", "interval_hour"),
    (r"every\s+(\d+)\s*min(?:ute)?s?", "interval_min"),
    (r"every\s+(\d+)\s*hours?", "interval_hour"),
    # Simple hourly/minutely without number: "every hour", "щогодини", "каждый час"
    (r"(?:every\s+hour|hourly)", "every_hour"),
    (r"щогодин[иі]?", "every_hour"),
    (r"каждый\s+час", "every_hour"),
    (r"(?:every\s+minute|minutely)", "every_minute"),
    (r"щохвилин[иі]?", "every_minute"),
    (r"каждую\s+минуту", "every_minute"),
    # "о 9 ранку щодня"
    (r"о\s+(\d{1,2})(?::(\d{2}))?\s+(?:ранку|ранок)", "daily"),
    # weekdays (UA)
    # Numbering follows APScheduler convention: 0=Mon..6=Sun
    (r"(?:що)?понеділ[оь]?к\w*\s+о?\s*(\d{1,2})(?::(\d{2}))?", "weekly_mon"),
    (r"(?:що)?вівтор[оо]?к\w*\s+о?\s*(\d{1,2})(?::(\d{2}))?", "weekly_tue"),
    (r"(?:що)?серед[аиу]\w*\s+о?\s*(\d{1,2})(?::(\d{2}))?", "weekly_wed"),
    (r"(?:що)?четвер\w*\s+о?\s*(\d{1,2})(?::(\d{2}))?", "weekly_thu"),
    (r"(?:що)?п'?ятниц[яіу]\w*\s+о?\s*(\d{1,2})(?::(\d{2}))?", "weekly_fri"),
    (r"щоп'?ятниц[іи]\s+о?\s*(\d{1,2})(?::(\d{2}))?", "weekly_fri"),
    (r"(?:що)?субот[аиу]\w*\s+о?\s*(\d{1,2})(?::(\d{2}))?", "weekly_sat"),
    (r"(?:що)?неділ[яюі]\w*\s+о?\s*(\d{1,2})(?::(\d{2}))?", "weekly_sun"),
    (r"щосубот[иі]\s+о?\s*(\d{1,2})(?::(\d{2}))?", "weekly_sat"),
    (r"щонеділ[іи]\s+о?\s*(\d{1,2})(?::(\d{2}))?", "weekly_sun"),
    # weekdays (EN)
    (r"(?:every\s+)?monday\w*\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?", "weekly_mon"),
    (r"(?:every\s+)?tuesday\w*\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?", "weekly_tue"),
    (r"(?:every\s+)?wednesday\w*\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?", "weekly_wed"),
    (r"(?:every\s+)?thursday\w*\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?", "weekly_thu"),
    (r"(?:every\s+)?friday\w*\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?", "weekly_fri"),
    (r"(?:every\s+)?saturday\w*\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?", "weekly_sat"),
    (r"(?:every\s+)?sunday\w*\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?", "weekly_sun"),
    # weekdays (RU)
    (r"(?:каждый\s+)?понедельник\w*\s+(?:в\s+)?(\d{1,2})(?::(\d{2}))?", "weekly_mon"),
    (r"(?:каждый\s+)?вторник\w*\s+(?:в\s+)?(\d{1,2})(?::(\d{2}))?", "weekly_tue"),
    (r"(?:каждую?\s+)?сред[ауе]\w*\s+(?:в\s+)?(\d{1,2})(?::(\d{2}))?", "weekly_wed"),
    (r"(?:каждый\s+)?четверг\w*\s+(?:в\s+)?(\d{1,2})(?::(\d{2}))?", "weekly_thu"),
    (r"(?:каждую?\s+)?пятниц[ауе]\w*\s+(?:в\s+)?(\d{1,2})(?::(\d{2}))?", "weekly_fri"),
    (r"(?:каждую?\s+)?суббот[ауе]\w*\s+(?:в\s+)?(\d{1,2})(?::(\d{2}))?", "weekly_sat"),
    (r"(?:каждое?\s+)?воскресень[еи]\w*\s+(?:в\s+)?(\d{1,2})(?::(\d{2}))?", "weekly_sun"),
    # Monthly UA: "кожного 1-го о 9", "щомісяця 15 о 10:30"
    (r"кожного\s+(\d{1,2})[-\u2011]?(?:го)?\s+о\s+(\d{1,2})(?::(\d{2}))?", "monthly"),
    (r"щомісяця\s+(\d{1,2})\s+о\s+(\d{1,2})(?::(\d{2}))?", "monthly"),
    # Monthly EN: "every 1st at 9", "monthly on 15 at 10:30"
    (r"monthly\s+(?:on\s+)?(\d{1,2})\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?", "monthly"),
    (r"every\s+(\d{1,2})(?:st|nd|rd|th)\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?", "monthly"),
    # Monthly RU: "каждого 1-го в 9"
    (r"каждого\s+(\d{1,2})[-\u2011]?(?:го)?\s+в\s+(\d{1,2})(?::(\d{2}))?", "monthly"),
]

# APScheduler day_of_week names — unambiguous, no POSIX numbering confusion
_WEEKDAY_MAP: dict[str, str] = {
    "weekly_mon": "mon",
    "weekly_tue": "tue",
    "weekly_wed": "wed",
    "weekly_thu": "thu",
    "weekly_fri": "fri",
    "weekly_sat": "sat",
    "weekly_sun": "sun",
}

_SCHEDULE_KEYWORDS: list[str] = [
    "нагадай",
    "нагадати",
    "напомни",
    "напомнить",
    "remind",
    "через",
    "щодня",
    "кожні",
    "кожен",
    "кожного",
    "каждый",
    "каждого",
    "every day",
    "every hour",
    "every min",
    "monthly",
    "щомісяця",
    "schedule",
    "запланувати",
    "запланируй",
]

# Patterns that require regex match (avoid false positives from bare "in 1" etc.)
_SCHEDULE_REGEX_PATTERNS: list[str] = [
    r"in\s+\d+\s*(?:min|hour|day)",
]

_MAX_PARSE_LENGTH = 500  # ReDoS protection: truncate before regex matching


def detect_schedule_intent(text: str) -> bool:
    """Чи містить текст намір створити розклад."""
    lower = text[:_MAX_PARSE_LENGTH].lower().strip()
    if any(kw in lower for kw in _SCHEDULE_KEYWORDS):
        return True
    return any(re.search(p, lower) for p in _SCHEDULE_REGEX_PATTERNS)


def parse_schedule(text: str, tz: str = "UTC") -> ParsedSchedule:
    """Парсити NL текст у параметри cron job.

    Args:
        text: Natural language schedule description.
        tz: IANA timezone for relative time calculations (e.g. "Europe/Kyiv").
    """
    lower = text[:_MAX_PARSE_LENGTH].lower().strip()

    try:
        tzinfo = ZoneInfo(tz) if tz != "UTC" else UTC
    except (KeyError, ValueError):
        tzinfo = UTC

    # 1. Try relative time ("через 30 хвилин")
    for pattern, unit in _RELATIVE_PATTERNS:
        m = re.search(pattern, lower)
        if m:
            amount = int(m.group(1))
            delta = _unit_to_timedelta(amount, unit)
            now = datetime.now(tz=tzinfo)
            target = now + delta
            return ParsedSchedule(
                cron_type=CronType.ONE_SHOT,
                at=target.astimezone(UTC).isoformat(),
                confidence=0.9,
                description=f"через {amount} {unit}",
            )

    # 2. Try recurring patterns
    for pattern, kind in _RECURRING_PATTERNS:
        m = re.search(pattern, lower)
        if m:
            return _build_recurring(m, kind)

    return ParsedSchedule(cron_type=CronType.ONE_SHOT, confidence=0.0)


def _unit_to_timedelta(amount: int, unit: str) -> timedelta:
    if unit == "minutes":
        return timedelta(minutes=amount)
    if unit == "hours":
        return timedelta(hours=amount)
    if unit == "days":
        return timedelta(days=amount)
    return timedelta(minutes=amount)


def _validate_time(hour: int, minute: int) -> bool:
    """Validate hour (0-23) and minute (0-59)."""
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _build_recurring(match: re.Match, kind: str) -> ParsedSchedule:
    if kind == "every_hour":
        return ParsedSchedule(
            cron_type=CronType.INTERVAL,
            every="1h",
            confidence=0.9,
            description="щогодини",
        )

    if kind == "every_minute":
        return ParsedSchedule(
            cron_type=CronType.INTERVAL,
            every="1m",
            confidence=0.9,
            description="щохвилини",
        )

    if kind == "daily":
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if not _validate_time(hour, minute):
            return ParsedSchedule(cron_type=CronType.ONE_SHOT, confidence=0.0)
        return ParsedSchedule(
            cron_type=CronType.RECURRING,
            cron=f"{minute} {hour} * * *",
            confidence=0.9,
            description=f"щодня о {hour}:{minute:02d}",
        )

    if kind == "interval_min":
        mins = int(match.group(1))
        if mins <= 0:
            return ParsedSchedule(cron_type=CronType.ONE_SHOT, confidence=0.0)
        return ParsedSchedule(
            cron_type=CronType.INTERVAL,
            every=f"{mins}m",
            confidence=0.85,
            description=f"кожні {mins} хвилин",
        )

    if kind == "interval_hour":
        hours = int(match.group(1))
        if hours <= 0:
            return ParsedSchedule(cron_type=CronType.ONE_SHOT, confidence=0.0)
        return ParsedSchedule(
            cron_type=CronType.INTERVAL,
            every=f"{hours}h",
            confidence=0.85,
            description=f"кожні {hours} годин",
        )

    if kind == "monthly":
        day = int(match.group(1))
        hour = int(match.group(2))
        minute = int(match.group(3) or 0)
        if not (1 <= day <= 31 and _validate_time(hour, minute)):
            return ParsedSchedule(cron_type=CronType.ONE_SHOT, confidence=0.0)
        return ParsedSchedule(
            cron_type=CronType.RECURRING,
            cron=f"{minute} {hour} {day} * *",
            confidence=0.85,
            description=f"кожного {day}-го о {hour}:{minute:02d}",
        )

    if kind in _WEEKDAY_MAP:
        dow = _WEEKDAY_MAP[kind]
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if not _validate_time(hour, minute):
            return ParsedSchedule(cron_type=CronType.ONE_SHOT, confidence=0.0)
        return ParsedSchedule(
            cron_type=CronType.RECURRING,
            cron=f"{minute} {hour} * * {dow}",
            confidence=0.85,
            description=f"{kind.replace('weekly_', '')} о {hour}:{minute:02d}",
        )

    return ParsedSchedule(cron_type=CronType.ONE_SHOT, confidence=0.0)


def format_confirmation(name: str, parsed: ParsedSchedule) -> str:
    """Текст підтвердження для користувача."""
    schedule_str = parsed.cron or parsed.every or parsed.at[:19]
    return (
        f"Створити завдання '{name}'?\n"
        f"  Розклад: {parsed.description}\n"
        f"  Тип: {parsed.cron_type}\n"
        f"  Вираз: {schedule_str}"
    )
