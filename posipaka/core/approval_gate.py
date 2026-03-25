"""ApprovalGate — підтвердження деструктивних дій."""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from loguru import logger

from posipaka.core.agent_types import PendingAction

if TYPE_CHECKING:
    from posipaka.core.hooks.manager import HookManager
    from posipaka.core.tools.registry import ToolRegistry
    from posipaka.security.audit import AuditLogger

APPROVE_WORDS = frozenset(
    {
        "так",
        "yes",
        "ок",
        "ok",
        "давай",
        "yep",
        "yeah",
        "sure",
        "да",
        "go",
        "+",
    }
)
DENY_WORDS = frozenset(
    {
        "ні",
        "no",
        "cancel",
        "відміна",
        "стоп",
        "nah",
        "nope",
        "не треба",
        "нет",
        "-",
    }
)
ALL_TRIGGER_WORDS = APPROVE_WORDS | DENY_WORDS


class ApprovalGate:
    """Управління approval flow для деструктивних дій."""

    def __init__(
        self,
        tools: ToolRegistry,
        audit: AuditLogger,
        hooks: HookManager,
        timeout_seconds: float = 300.0,
    ) -> None:
        self._tools = tools
        self._audit = audit
        self._hooks = hooks
        self._timeout = timeout_seconds
        self._pending: dict[str, PendingAction] = {}

    def requires_approval(self, tool_name: str) -> bool:
        """Чи потребує дія підтвердження."""
        tool_def = self._tools.get(tool_name)
        return bool(tool_def and tool_def.requires_approval)

    def request(
        self,
        tool_name: str,
        tool_input: dict,
        session_id: str,
        user_id: str = "",
    ) -> PendingAction:
        """Створити pending approval request."""
        action = PendingAction(
            id=str(uuid.uuid4()),
            tool_name=tool_name,
            tool_input=tool_input,
            session_id=session_id,
            user_id=user_id,
            description=self._tools.describe_action(tool_name, tool_input),
        )
        self._pending[action.id] = action
        self._audit.log(
            "approval_requested",
            {"action_id": action.id, "tool": tool_name},
        )
        return action

    async def process_response(self, content: str, session_id: str) -> str | None:
        """Обробити відповідь на approval. None якщо немає pending для цієї сесії."""
        from posipaka.core.hooks.manager import HookEvent

        for action_id, action in list(self._pending.items()):
            if action.session_id != session_id:
                continue

            # Check timeout
            if time.time() - action.created_at > self._timeout:
                del self._pending[action_id]
                return "Час підтвердження вичерпано. Дія скасована."

            lower = content.lower().strip()
            if lower in APPROVE_WORDS:
                del self._pending[action_id]
                self._audit.log("approval_granted", {"action_id": action_id})
                await self._hooks.emit(HookEvent.APPROVAL_GRANTED, {"action_id": action_id})
                try:
                    result = await self._tools.execute(action.tool_name, action.tool_input)
                    return f"Виконано: {result}"
                except Exception as e:
                    return f"Помилка при виконанні: {e}"
            elif lower in DENY_WORDS:
                del self._pending[action_id]
                self._audit.log("approval_denied", {"action_id": action_id})
                await self._hooks.emit(HookEvent.APPROVAL_DENIED, {"action_id": action_id})
                return "Дію скасовано."

        return None

    async def cleanup_expired(self) -> None:
        """Видалити прострочені approval requests."""
        now = time.time()
        expired = [
            aid for aid, action in self._pending.items() if now - action.created_at > self._timeout
        ]
        for aid in expired:
            action = self._pending.pop(aid)
            logger.info(f"Approval expired: {aid} ({action.tool_name})")
            self._audit.log("approval_expired", {"action_id": aid})

    def has_pending(self, session_id: str) -> bool:
        """Чи є pending approvals для цієї сесії."""
        return any(a.session_id == session_id for a in self._pending.values())

    @property
    def pending_approvals(self) -> dict[str, PendingAction]:
        """Доступ до pending approvals (backward compat)."""
        return self._pending
