"""Session management — persistent, deterministic session IDs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    id: str
    user_id: str
    channel: str
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """Update last_active timestamp."""
        self.last_active = time.time()


class SessionManager:
    """Керування сесіями з детерміністичними ID.

    Session ID = "{user_id}:{channel}" — стабільний, переживає рестарт.
    Повідомлення прив'язані до цього ID в SQLite/ChromaDB/Tantivy,
    тому після рестарту агент підхоплює попередній контекст.
    """

    MAX_CONCURRENT_SESSIONS_PER_USER = 3
    MAX_SESSION_TTL_SECONDS = 86400

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._named_sessions: dict[str, Session] = {}

    @staticmethod
    def make_session_id(user_id: str, channel: str) -> str:
        """Deterministic session ID: user_id:channel."""
        return f"{user_id}:{channel}"

    def create(self, user_id: str, channel: str) -> Session:
        user_sessions = [s for s in self._sessions.values() if s.user_id == user_id]
        if len(user_sessions) >= self.MAX_CONCURRENT_SESSIONS_PER_USER:
            oldest = min(user_sessions, key=lambda s: s.last_active)
            self.close(oldest.id)

        session = Session(
            id=self.make_session_id(user_id, channel),
            user_id=user_id,
            channel=channel,
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def cleanup_expired(self) -> None:
        """Remove sessions older than MAX_SESSION_TTL_SECONDS."""
        now = time.time()
        expired = [
            sid
            for sid, s in self._sessions.items()
            if now - s.last_active > self.MAX_SESSION_TTL_SECONDS
        ]
        for sid in expired:
            self._sessions.pop(sid, None)

    def get_or_create(self, user_id: str, channel: str) -> Session:
        if len(self._sessions) > 50:
            self.cleanup_expired()

        session_id = self.make_session_id(user_id, channel)
        existing = self._sessions.get(session_id)
        if existing:
            existing.touch()
            return existing
        return self.create(user_id, channel)

    def get_or_create_named(self, name: str, user_id: str, channel: str) -> Session:
        """Отримати або створити persistent named session."""
        existing = self._named_sessions.get(name)
        if existing and existing.id in self._sessions:
            existing.touch()
            return existing
        session = self.create(user_id, channel)
        session.metadata["session_name"] = name
        self._named_sessions[name] = session
        return session

    def get_named(self, name: str) -> Session | None:
        """Отримати named session якщо існує."""
        session = self._named_sessions.get(name)
        if session and session.id in self._sessions:
            return session
        return None

    def list_active(self) -> list[Session]:
        return list(self._sessions.values())

    def close(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._named_sessions = {k: v for k, v in self._named_sessions.items() if v.id != session_id}
