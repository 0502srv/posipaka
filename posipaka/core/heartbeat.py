"""Heartbeat Engine — проактивна серцебиття агента."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from posipaka.core.llm import LLMClient

HEARTBEAT_OK_TOKEN = "HEARTBEAT_OK"

HEARTBEAT_SYSTEM = """\
You are a proactive monitoring agent. Your job is to check the user's \
HEARTBEAT.md checklist against the provided data and decide:

1. If something IMPORTANT requires the user's attention → write a concise alert message.
2. If nothing important → respond with exactly: HEARTBEAT_OK

Rules:
- Be concise (1-3 sentences max per alert)
- Don't notify about newsletters, spam, or routine automated emails
- Follow the user's "don't bother me" instructions strictly
- Use the user's preferred language
"""


@dataclass
class HeartbeatResult:
    action: str  # "silent" | "notified"
    reason: str = ""
    content: str = ""


@dataclass
class QuickCheckResult:
    has_potential_alerts: bool = False
    data: dict = None

    def __post_init__(self):
        if self.data is None:
            self.data = {}

    def to_prompt(self) -> str:
        parts = ["Current data for heartbeat check:\n"]
        for key, value in self.data.items():
            parts.append(f"## {key}\n{value}\n")
        return "\n".join(parts)


class HeartbeatEngine:
    """
    Проактивний моніторинг за розкладом.

    Алгоритм:
    1. Перевірити активні години → якщо ні: SILENT
    2. Завантажити HEARTBEAT.md
    3. Виконати ДЕШЕВІ перевірки (БЕЗ LLM)
    4. Якщо нічого → HEARTBEAT_OK (без LLM!)
    5. Якщо є щось → LLM оцінює важливість
    6. LLM → повідомлення або HEARTBEAT_OK
    """

    def __init__(
        self,
        data_dir: Path,
        active_hours_start: int = 8,
        active_hours_end: int = 23,
        timezone: str = "Europe/Kyiv",
    ) -> None:
        self._data_dir = data_dir
        self._hb_path = data_dir / "HEARTBEAT.md"
        self._active_start = active_hours_start
        self._active_end = active_hours_end
        self._timezone = timezone
        self._last_tick: float = 0
        self._notifications_today: int = 0

    async def tick(
        self,
        llm: LLMClient | None = None,
        quick_check_fn: Any = None,
        send_fn: Any = None,
    ) -> HeartbeatResult:
        """Один цикл heartbeat."""
        if not self._is_active_hours():
            return HeartbeatResult(action="silent", reason="outside_active_hours")

        hb_md = self._load_heartbeat_md()
        if not hb_md:
            return HeartbeatResult(action="silent", reason="no_heartbeat_md")

        # Quick checks (no LLM)
        quick = QuickCheckResult()
        if quick_check_fn:
            try:
                quick = await quick_check_fn()
            except Exception as e:
                logger.error(f"Heartbeat quick check error: {e}")

        if not quick.has_potential_alerts:
            self._last_tick = time.time()
            return HeartbeatResult(action="silent", reason=HEARTBEAT_OK_TOKEN)

        # LLM evaluation
        if not llm:
            return HeartbeatResult(action="silent", reason="no_llm")

        try:
            system = f"{HEARTBEAT_SYSTEM}\n\n# User Heartbeat Config\n{hb_md}"
            response = await llm.complete(
                system=system,
                messages=[{"role": "user", "content": quick.to_prompt()}],
            )
            content = response.get("content", "").strip()

            if HEARTBEAT_OK_TOKEN in content:
                self._last_tick = time.time()
                return HeartbeatResult(action="silent", reason=HEARTBEAT_OK_TOKEN)

            # Notify
            self._notifications_today += 1
            self._last_tick = time.time()

            if send_fn:
                await send_fn(content)

            return HeartbeatResult(action="notified", content=content)
        except Exception as e:
            logger.error(f"Heartbeat LLM error: {e}")
            return HeartbeatResult(action="silent", reason=f"error: {e}")

    def _is_active_hours(self) -> bool:
        """Перевірити чи зараз активні години."""
        try:
            from datetime import datetime

            import pytz

            tz = pytz.timezone(self._timezone)
            now = datetime.now(tz)
            return self._active_start <= now.hour < self._active_end
        except ImportError:
            from datetime import datetime

            now = datetime.now(UTC)
            return self._active_start <= now.hour < self._active_end

    def _load_heartbeat_md(self) -> str:
        if self._hb_path.exists():
            return self._hb_path.read_text(encoding="utf-8")
        return ""

    def get_status(self) -> str:
        last = f"{time.time() - self._last_tick:.0f}s ago" if self._last_tick else "never"
        active = "ACTIVE" if self._is_active_hours() else "SLEEPING"
        return (
            f"Heartbeat: {active}\n"
            f"Active hours: {self._active_start}:00–{self._active_end}:00 "
            f"({self._timezone})\n"
            f"Last tick: {last}\n"
            f"Notifications today: {self._notifications_today}"
        )
