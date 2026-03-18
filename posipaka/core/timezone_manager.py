"""Per-user timezone management.

PRINCIPLE: all user-facing time operations use USER tz,
not server tz and not SOUL_TIMEZONE (when user tz is known).
Internal storage always uses UTC.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiosqlite
from loguru import logger

# ---------------------------------------------------------------------------
# City / alias mappings for detection & fuzzy match
# ---------------------------------------------------------------------------

CITY_TO_TZ: dict[str, str] = {
    # Ukrainian cities
    "київ": "Europe/Kyiv",
    "kyiv": "Europe/Kyiv",
    "kiev": "Europe/Kyiv",
    "львів": "Europe/Kyiv",
    "lviv": "Europe/Kyiv",
    "харків": "Europe/Kyiv",
    "kharkiv": "Europe/Kyiv",
    "одеса": "Europe/Kyiv",
    "odesa": "Europe/Kyiv",
    "odessa": "Europe/Kyiv",
    "дніпро": "Europe/Kyiv",
    "dnipro": "Europe/Kyiv",
    # Europe
    "варшав": "Europe/Warsaw",
    "warsaw": "Europe/Warsaw",
    "берлін": "Europe/Berlin",
    "berlin": "Europe/Berlin",
    "лондон": "Europe/London",
    "london": "Europe/London",
    "paris": "Europe/Paris",
    "париж": "Europe/Paris",
    "мадрид": "Europe/Madrid",
    "madrid": "Europe/Madrid",
    "рим": "Europe/Rome",
    "rome": "Europe/Rome",
    "прага": "Europe/Prague",
    "prague": "Europe/Prague",
    "москва": "Europe/Moscow",
    "moscow": "Europe/Moscow",
    # Americas
    "нью-йорк": "America/New_York",
    "new york": "America/New_York",
    "лос-анджелес": "America/Los_Angeles",
    "los angeles": "America/Los_Angeles",
    "чикаго": "America/Chicago",
    "chicago": "America/Chicago",
    "торонто": "America/Toronto",
    "toronto": "America/Toronto",
    # Asia / Middle East
    "токіо": "Asia/Tokyo",
    "tokyo": "Asia/Tokyo",
    "дубай": "Asia/Dubai",
    "dubai": "Asia/Dubai",
    "бангкок": "Asia/Bangkok",
    "bangkok": "Asia/Bangkok",
    "сінгапур": "Asia/Singapore",
    "singapore": "Asia/Singapore",
    "шанхай": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    # Oceania
    "сідней": "Australia/Sydney",
    "sydney": "Australia/Sydney",
}

COMMON_ALIASES: dict[str, str] = {
    "ukraine": "Europe/Kyiv",
    "україна": "Europe/Kyiv",
    "poland": "Europe/Warsaw",
    "польща": "Europe/Warsaw",
    "germany": "Europe/Berlin",
    "німеччина": "Europe/Berlin",
    "utc": "UTC",
    "gmt": "UTC",
    "est": "America/New_York",
    "edt": "America/New_York",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "cet": "Europe/Berlin",
    "cest": "Europe/Berlin",
    "eet": "Europe/Kyiv",
    "eest": "Europe/Kyiv",
    "jst": "Asia/Tokyo",
    "ist": "Asia/Kolkata",
    "aest": "Australia/Sydney",
}

# Pattern for explicit tz mentions like "UTC+3", "GMT-5"
_UTC_OFFSET_RE = re.compile(
    r"\b(?:utc|gmt)\s*([+-])\s*(\d{1,2})(?::(\d{2}))?\b", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Dataclass for stored timezone entry
# ---------------------------------------------------------------------------

@dataclass
class TimezoneEntry:
    user_id: str
    tz_name: str
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ---------------------------------------------------------------------------
# UserTimezoneManager
# ---------------------------------------------------------------------------

class UserTimezoneManager:
    """
    Central per-user timezone manager.

    Storage: in-memory dict + optional SQLite persistence.
    Fallback chain: explicit set -> detected -> server tz -> UTC.
    """

    _CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS user_timezones (
            user_id   TEXT PRIMARY KEY,
            tz_name   TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """

    def __init__(
        self,
        *,
        default_tz: str = "UTC",
        db_path: Path | None = None,
    ) -> None:
        self._default_tz = self._validate_tz(default_tz) or "UTC"
        self._db_path = db_path
        self._cache: dict[str, str] = {}
        self._db_initialized = False

    # -- public API ---------------------------------------------------------

    async def set_timezone(self, user_id: str, tz_name: str) -> str:
        """
        Set timezone for *user_id*. Validates via ZoneInfo.
        Falls back to fuzzy match if exact name is invalid.
        Returns the resolved IANA tz name.

        Raises ValueError if timezone cannot be resolved at all.
        """
        resolved = self._validate_tz(tz_name)
        if resolved is None:
            resolved = self._fuzzy_match(tz_name)
        if resolved is None:
            raise ValueError(
                f"Unknown timezone: {tz_name!r}. "
                f"Use IANA name like 'Europe/Kyiv' or city name."
            )

        self._cache[user_id] = resolved
        await self._persist(user_id, resolved)
        logger.info("Timezone set: user={} tz={}", user_id, resolved)
        return resolved

    async def get_timezone(self, user_id: str) -> ZoneInfo:
        """
        Return ZoneInfo for *user_id*.
        Fallback: server default -> UTC.
        """
        tz_name = await self._resolve_tz_name(user_id)
        try:
            return ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, KeyError):
            logger.warning(
                "Invalid stored tz '{}' for user {}, falling back to UTC",
                tz_name,
                user_id,
            )
            return ZoneInfo("UTC")

    def detect_from_message(self, text: str) -> str | None:
        """
        Try to detect timezone from message text (city names, UTC offsets).
        Returns IANA tz name or None.
        """
        text_lower = text.lower()

        # 1. Check city keywords
        for keyword, tz in CITY_TO_TZ.items():
            if keyword in text_lower:
                logger.debug("Detected timezone {} from keyword '{}'", tz, keyword)
                return tz

        # 2. Check UTC+N / GMT-N patterns
        match = _UTC_OFFSET_RE.search(text)
        if match:
            sign, hours_s, minutes_s = match.groups()
            hours = int(hours_s)
            minutes = int(minutes_s) if minutes_s else 0
            if sign == "-":
                hours, minutes = -hours, -minutes
            tz = _offset_to_iana(hours, minutes)
            if tz:
                logger.debug("Detected timezone {} from UTC offset", tz)
                return tz

        return None

    async def get_user_now(self, user_id: str) -> datetime:
        """Current datetime in user's timezone."""
        tz = await self.get_timezone(user_id)
        return datetime.now(tz)

    async def get_user_time_str(
        self,
        user_id: str,
        fmt: str = "%A, %d %B %Y, %H:%M",
    ) -> str:
        """Formatted current time string in user's timezone."""
        now = await self.get_user_now(user_id)
        return now.strftime(fmt)

    async def to_user_time(self, user_id: str, dt: datetime) -> datetime:
        """
        Convert any datetime to user's timezone.
        If *dt* is naive, it is assumed to be UTC.
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        tz = await self.get_timezone(user_id)
        return dt.astimezone(tz)

    async def to_utc(self, user_id: str, user_dt: datetime) -> datetime:
        """
        Convert user-local datetime to UTC.
        If *user_dt* is naive, it is assumed to be in user's timezone.
        """
        if user_dt.tzinfo is None:
            tz = await self.get_timezone(user_id)
            user_dt = user_dt.replace(tzinfo=tz)
        return user_dt.astimezone(ZoneInfo("UTC"))

    async def list_users(self) -> dict[str, str]:
        """Return dict of user_id -> tz_name for all known users."""
        result = dict(self._cache)

        # Merge from DB (DB is source of truth, cache may be stale)
        if self._db_path and self._db_path.exists():
            await self._ensure_db()
            async with aiosqlite.connect(str(self._db_path)) as db, db.execute(
                "SELECT user_id, tz_name FROM user_timezones"
            ) as cursor:
                async for row in cursor:
                    result.setdefault(row[0], row[1])

        return result

    # -- Integration helper -------------------------------------------------

    async def format_for_system_prompt(self, user_id: str) -> str:
        """
        Return timezone context line for system prompt injection.

        Example output:
            Current date and time: Tuesday, 17 March 2026, 15:42
            User timezone: Europe/Kyiv
            IMPORTANT: Always use user's timezone for scheduling, reminders,
            and time references. Never use UTC unless explicitly asked.
        """
        user_now = await self.get_user_now(user_id)
        tz_name = await self._resolve_tz_name(user_id)
        offset = user_now.strftime("%z")  # e.g. "+0300"
        formatted_offset = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset

        return (
            f"Current date and time: {user_now.strftime('%A, %d %B %Y, %H:%M')}\n"
            f"User timezone: {tz_name} (UTC{formatted_offset})\n"
            f"IMPORTANT: Always use user's timezone for scheduling, reminders, "
            f"and time references. Never use UTC unless explicitly asked."
        )

    # -- Private helpers ----------------------------------------------------

    async def _resolve_tz_name(self, user_id: str) -> str:
        """Resolve tz name string: cache -> DB -> default."""
        if user_id in self._cache:
            return self._cache[user_id]

        # Try loading from DB
        tz_name = await self._load_from_db(user_id)
        if tz_name:
            self._cache[user_id] = tz_name
            return tz_name

        return self._default_tz

    @staticmethod
    def _validate_tz(tz_name: str) -> str | None:
        """Return canonical tz name if valid, else None."""
        try:
            zi = ZoneInfo(tz_name)
            return str(zi)
        except (ZoneInfoNotFoundError, KeyError):
            return None

    @staticmethod
    def _fuzzy_match(user_input: str) -> str | None:
        """Match free-form text to an IANA tz name."""
        normalized = user_input.lower().strip().replace(" ", "_")

        # Direct alias
        if normalized in COMMON_ALIASES:
            return COMMON_ALIASES[normalized]

        # City map (substring)
        for keyword, tz in CITY_TO_TZ.items():
            if keyword in normalized:
                return tz

        # Try as-is with prefix guessing: "kyiv" -> "Europe/Kyiv"
        capitalized = "/".join(
            part.capitalize() for part in normalized.split("/")
        )
        if UserTimezoneManager._validate_tz(capitalized):
            return capitalized

        return None

    # -- SQLite persistence -------------------------------------------------

    async def _ensure_db(self) -> None:
        """Create table if it doesn't exist yet."""
        if self._db_initialized or not self._db_path:
            return
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(self._CREATE_TABLE_SQL)
            await db.commit()
        self._db_initialized = True

    async def _persist(self, user_id: str, tz_name: str) -> None:
        """Save timezone to SQLite if db_path configured."""
        if not self._db_path:
            return
        await self._ensure_db()
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                """
                INSERT INTO user_timezones (user_id, tz_name, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    tz_name = excluded.tz_name,
                    updated_at = excluded.updated_at
                """,
                (user_id, tz_name, now),
            )
            await db.commit()
        logger.debug("Persisted timezone for user {}: {}", user_id, tz_name)

    async def _load_from_db(self, user_id: str) -> str | None:
        """Load timezone from SQLite. Returns None if not found or no DB."""
        if not self._db_path or not self._db_path.exists():
            return None
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db, db.execute(
            "SELECT tz_name FROM user_timezones WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _offset_to_iana(hours: int, minutes: int = 0) -> str | None:
    """
    Best-effort mapping of a UTC offset to an IANA tz name.
    Returns None if no reasonable match found.
    """
    offset_map: dict[tuple[int, int], str] = {
        (-12, 0): "Etc/GMT+12",
        (-11, 0): "Pacific/Midway",
        (-10, 0): "Pacific/Honolulu",
        (-9, 0): "America/Anchorage",
        (-8, 0): "America/Los_Angeles",
        (-7, 0): "America/Denver",
        (-6, 0): "America/Chicago",
        (-5, 0): "America/New_York",
        (-4, 0): "America/Halifax",
        (-3, 0): "America/Sao_Paulo",
        (-2, 0): "Atlantic/South_Georgia",
        (-1, 0): "Atlantic/Azores",
        (0, 0): "UTC",
        (1, 0): "Europe/Berlin",
        (2, 0): "Europe/Kyiv",
        (3, 0): "Europe/Moscow",
        (3, 30): "Asia/Tehran",
        (4, 0): "Asia/Dubai",
        (4, 30): "Asia/Kabul",
        (5, 0): "Asia/Karachi",
        (5, 30): "Asia/Kolkata",
        (5, 45): "Asia/Kathmandu",
        (6, 0): "Asia/Dhaka",
        (7, 0): "Asia/Bangkok",
        (8, 0): "Asia/Shanghai",
        (9, 0): "Asia/Tokyo",
        (9, 30): "Australia/Darwin",
        (10, 0): "Australia/Sydney",
        (11, 0): "Pacific/Noumea",
        (12, 0): "Pacific/Auckland",
        (13, 0): "Pacific/Apia",
    }
    return offset_map.get((hours, minutes))
