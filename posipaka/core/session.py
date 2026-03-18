"""Session management."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Session:
    id: str
    user_id: str
    channel: str
    created_at: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class SessionManager:
    """Керування сесіями користувачів."""

    MAX_CONCURRENT_SESSIONS_PER_USER = 3

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, user_id: str, channel: str) -> Session:
        user_sessions = [s for s in self._sessions.values() if s.user_id == user_id]
        if len(user_sessions) >= self.MAX_CONCURRENT_SESSIONS_PER_USER:
            oldest = min(user_sessions, key=lambda s: s.created_at)
            self.close(oldest.id)

        session = Session(
            id=str(uuid.uuid4()),
            user_id=user_id,
            channel=channel,
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def get_or_create(self, user_id: str, channel: str) -> Session:
        for s in self._sessions.values():
            if s.user_id == user_id and s.channel == channel:
                return s
        return self.create(user_id, channel)

    def list_active(self) -> list[Session]:
        return list(self._sessions.values())

    def close(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
