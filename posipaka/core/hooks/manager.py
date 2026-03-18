"""HookManager — event-driven extensibility."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from loguru import logger


class HookEvent(StrEnum):
    # Message lifecycle
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_SENT = "message_sent"
    MESSAGE_EDITED = "message_edited"

    # Tool lifecycle
    BEFORE_TOOL_CALL = "before_tool_call"
    AFTER_TOOL_CALL = "after_tool_call"
    TOOL_ERROR = "tool_error"

    # Memory lifecycle
    BEFORE_COMPACTION = "before_compaction"
    AFTER_COMPACTION = "after_compaction"
    FACT_EXTRACTED = "fact_extracted"

    # Session lifecycle
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    SESSION_RESET = "session_reset"

    # Approval lifecycle
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"

    # Gateway lifecycle
    GATEWAY_START = "gateway_start"
    GATEWAY_STOP = "gateway_stop"
    CHANNEL_CONNECTED = "channel_connected"
    CHANNEL_DISCONNECTED = "channel_disconnected"

    # Agent lifecycle
    AGENT_START = "agent_start"
    AGENT_STOP = "agent_stop"
    AGENT_ERROR = "agent_error"

    # Scheduler
    JOB_TRIGGERED = "job_triggered"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"


class HookManager:
    """Менеджер хуків — event emitter з error isolation."""

    def __init__(self) -> None:
        self._handlers: dict[HookEvent, list[Callable]] = defaultdict(list)

    def on(self, event: HookEvent) -> Callable:
        """Decorator для реєстрації хука."""

        def decorator(func: Callable) -> Callable:
            self.register(event, func)
            return func

        return decorator

    def register(self, event: HookEvent, handler: Callable) -> None:
        """Зареєструвати handler для event."""
        self._handlers[event].append(handler)

    async def emit(self, event: HookEvent, data: dict[str, Any] | None = None) -> list[str]:
        """Emit event. Error isolation — один хук не ламає інших. Returns failed handler names."""
        handlers = self._handlers.get(event, [])
        failures: list[str] = []
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data or {})
                else:
                    handler(data or {})
            except Exception as e:
                name = getattr(handler, "__name__", repr(handler))
                logger.error(f"Hook error [{event.value}] in {name}: {e}")
                failures.append(name)
        return failures

    def list_hooks(self) -> dict[str, int]:
        """Кількість handlers per event."""
        return {event.value: len(handlers) for event, handlers in self._handlers.items()}
