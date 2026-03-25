"""Типи даних для Agent — AgentStatus, Message, PendingAction."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class AgentStatus(StrEnum):
    INITIALIZING = "initializing"
    READY = "ready"
    PROCESSING = "processing"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class Message:
    role: str
    content: str
    channel: str = "cli"
    user_id: str = ""
    username: str = ""
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    message_id: str = ""


@dataclass
class PendingAction:
    id: str
    tool_name: str
    tool_input: dict
    session_id: str
    user_id: str
    description: str
    created_at: float = field(default_factory=time.time)
