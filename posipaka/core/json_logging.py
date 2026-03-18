"""Structured JSON logging.

Provides production-ready JSON logging via loguru custom sink,
distributed tracing context, and secret scrubbing.
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Trace ID — per-request, propagated via contextvars
# ---------------------------------------------------------------------------

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
_log_context_var: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)


def get_trace_id() -> str:
    """Return current trace ID, generating one if absent."""
    tid = _trace_id_var.get()
    if not tid:
        tid = uuid.uuid4().hex[:16]
        _trace_id_var.set(tid)
    return tid


def set_trace_id(trace_id: str) -> None:
    """Explicitly set trace ID (e.g. from incoming request header)."""
    _trace_id_var.set(trace_id)


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------


@contextmanager
def add_context(**kwargs: Any) -> Generator[None, None, None]:
    """Context manager that adds extra fields to all log entries within scope.

    Usage::

        with add_context(user_id="u123", channel="telegram"):
            logger.info("processing message")
    """
    current = _log_context_var.get() or {}
    token = _log_context_var.set({**current, **kwargs})
    try:
        yield
    finally:
        _log_context_var.reset(token)


# ---------------------------------------------------------------------------
# Secret scrubbing
# ---------------------------------------------------------------------------

SCRUB_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-ant-[A-Za-z0-9\-]+"),  # Anthropic API key
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI API key
    re.compile(r"xoxb-[A-Za-z0-9\-]+"),  # Slack bot token
    re.compile(r"\d{10}:\w{35}"),  # Telegram bot token
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email addresses
]


def _scrub(text: str) -> str:
    """Remove sensitive data from log messages."""
    for pat in SCRUB_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


# ---------------------------------------------------------------------------
# JSONLogRecord dataclass
# ---------------------------------------------------------------------------


@dataclass
class JSONLogRecord:
    """Structured representation of a single log entry."""

    timestamp: str
    level: str
    message: str
    module: str
    function: str
    line: int
    context: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Custom loguru sink
# ---------------------------------------------------------------------------


def _build_record(message: Any) -> JSONLogRecord:
    """Convert a loguru message record into a JSONLogRecord."""
    record = message.record
    ctx = _log_context_var.get() or {}
    # Merge loguru extra with our contextvar context
    merged_ctx = {**ctx, **record.get("extra", {})}

    return JSONLogRecord(
        timestamp=record["time"].isoformat(),
        level=record["level"].name,
        message=_scrub(record["message"]),
        module=record.get("name", ""),
        function=record.get("function", ""),
        line=record.get("line", 0),
        context=merged_ctx,
        trace_id=_trace_id_var.get() or None,
    )


def json_sink(message: Any) -> None:
    """Loguru custom sink — writes one JSON object per line to stderr."""
    log_record = _build_record(message)
    sys.stderr.write(log_record.to_json() + "\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

_CONFIGURED = False


def _is_production() -> bool:
    """Auto-detect production environment."""
    env = os.environ.get("POSIPAKA_ENV", "").lower()
    if env in ("production", "prod"):
        return True
    return os.environ.get("DOCKER", "") == "1"


def setup_json_logging(
    production: bool | None = None,
    log_level: str = "INFO",
    log_dir: str | None = None,
) -> None:
    """Configure loguru for structured JSON or human-readable output.

    Args:
        production: Force production (JSON) mode.
                    ``None`` = auto-detect via ``POSIPAKA_ENV`` / ``DOCKER``.
        log_level: Minimum log level (default ``"INFO"``).
        log_dir: Directory for log files.  Defaults to ``~/.posipaka/logs``.
    """
    global _CONFIGURED  # noqa: PLW0603

    if production is None:
        production = _is_production()

    if log_dir is None:
        from pathlib import Path

        log_dir = str(Path("~/.posipaka/logs").expanduser())

    # Ensure log directory exists
    os.makedirs(log_dir, exist_ok=True)

    logger.remove()

    if production:
        # stderr — JSON structured (custom sink)
        logger.add(
            json_sink,
            level=log_level,
            format="{message}",  # sink receives the full record
        )
        # File — JSON lines (loguru serialize)
        logger.add(
            f"{log_dir}/posipaka.jsonl",
            serialize=True,
            rotation="50 MB",
            retention="30 days",
            compression="gz",
            level=log_level,
        )
    else:
        # Development: human-readable with colours
        logger.add(
            sys.stderr,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            ),
            level=log_level,
            colorize=True,
        )
        logger.add(
            f"{log_dir}/posipaka.log",
            rotation="10 MB",
            retention="7 days",
            level=log_level,
        )

    _CONFIGURED = True
    logger.debug(
        "Logging configured",
        mode="json" if production else "human",
        level=log_level,
    )
