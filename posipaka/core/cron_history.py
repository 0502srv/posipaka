"""CronHistory — execution log + dead letter queue for cron jobs.

Two tables:
    cron_executions — complete execution log (success/failure/running)
    cron_dlq        — dead letter queue for jobs that exhausted retries

DLQ allows manual inspection and retry of permanently failed jobs.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

__all__ = ["CronHistory"]

_MAX_TEXT_LENGTH = 2000


class CronHistory:
    """SQLite-backed cron execution history with dead letter queue."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._create_tables()
        logger.debug("CronHistory initialized")

    def _ensure_conn(self) -> sqlite3.Connection:
        """Guard: raise if init() was not called."""
        if self._conn is None:
            raise RuntimeError("CronHistory not initialized — call init() first")
        return self._conn

    def _create_tables(self) -> None:
        self._ensure_conn().executescript("""
            CREATE TABLE IF NOT EXISTS cron_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                job_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_sec REAL,
                status TEXT NOT NULL DEFAULT 'running',
                result TEXT,
                error TEXT,
                delivery_mode TEXT,
                target_channel TEXT,
                target_user_id TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_cron_exec_job_id
                ON cron_executions(job_id);
            CREATE INDEX IF NOT EXISTS idx_cron_exec_started
                ON cron_executions(started_at);

            CREATE TABLE IF NOT EXISTS cron_dlq (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                job_name TEXT NOT NULL,
                error TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                resolved_by TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
            );

            CREATE INDEX IF NOT EXISTS idx_cron_dlq_status
                ON cron_dlq(status);
            CREATE INDEX IF NOT EXISTS idx_cron_dlq_created
                ON cron_dlq(created_at);
        """)

    # ── Execution log ───────────────────────────────────────────

    def record_start(self, job_id: str, job_name: str) -> int:
        """Record execution start. Returns execution ID."""
        with self._lock:
            conn = self._ensure_conn()
            now = datetime.now(UTC).isoformat()
            cursor = conn.execute(
                "INSERT INTO cron_executions (job_id, job_name, started_at, status) "
                "VALUES (?, ?, ?, 'running')",
                (job_id, job_name, now),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def record_success(
        self,
        execution_id: int,
        result: str,
        delivery_mode: str = "",
        target_channel: str = "",
        target_user_id: str = "",
        duration_sec: float = 0.0,
    ) -> None:
        with self._lock:
            conn = self._ensure_conn()
            now = datetime.now(UTC).isoformat()
            conn.execute(
                "UPDATE cron_executions "
                "SET finished_at=?, status='success', result=?, duration_sec=?, "
                "    delivery_mode=?, target_channel=?, target_user_id=? "
                "WHERE id=?",
                (
                    now,
                    result[:_MAX_TEXT_LENGTH],
                    duration_sec,
                    delivery_mode,
                    target_channel,
                    target_user_id,
                    execution_id,
                ),
            )
            conn.commit()

    def record_failure(self, execution_id: int, error: str) -> None:
        with self._lock:
            conn = self._ensure_conn()
            now = datetime.now(UTC).isoformat()
            conn.execute(
                "UPDATE cron_executions SET finished_at=?, status='failed', error=? WHERE id=?",
                (now, error[:_MAX_TEXT_LENGTH], execution_id),
            )
            conn.commit()

    def get_runs(
        self,
        job_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._ensure_conn()
            if job_id:
                rows = conn.execute(
                    "SELECT * FROM cron_executions WHERE job_id=? ORDER BY started_at DESC LIMIT ?",
                    (job_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM cron_executions ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def get_stats(self, job_id: str) -> dict[str, Any]:
        """Stats: total, success, failed, avg_duration_sec."""
        with self._lock:
            conn = self._ensure_conn()
            row = conn.execute(
                "SELECT "
                "  COUNT(*) as total, "
                "  SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success, "
                "  SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed, "
                "  AVG(CASE WHEN status='success' THEN duration_sec END) as avg_duration "
                "FROM cron_executions WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if not row:
                return {"total": 0, "success": 0, "failed": 0, "avg_duration": 0}
            result = dict(row)
            result["avg_duration"] = round(result["avg_duration"] or 0, 2)
            return result

    # ── Dead Letter Queue ───────────────────────────────────────

    def add_to_dlq(
        self,
        job_id: str,
        job_name: str,
        error: str,
        attempts: int = 1,
    ) -> int:
        """Add failed job to dead letter queue. Returns DLQ entry ID."""
        with self._lock:
            conn = self._ensure_conn()
            now = datetime.now(UTC).isoformat()
            cursor = conn.execute(
                "INSERT INTO cron_dlq (job_id, job_name, error, attempts, created_at, status) "
                "VALUES (?, ?, ?, ?, ?, 'pending')",
                (job_id, job_name, error[:_MAX_TEXT_LENGTH], attempts, now),
            )
            conn.commit()
            logger.warning(f"Job '{job_name}' added to DLQ after {attempts} attempts")
            return cursor.lastrowid or 0

    def get_dlq(
        self,
        status: str = "pending",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get DLQ entries."""
        with self._lock:
            conn = self._ensure_conn()
            rows = conn.execute(
                "SELECT * FROM cron_dlq WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def resolve_dlq(self, dlq_id: int, resolved_by: str = "manual") -> bool:
        """Mark DLQ entry as resolved (manual retry or acknowledged)."""
        with self._lock:
            conn = self._ensure_conn()
            now = datetime.now(UTC).isoformat()
            cursor = conn.execute(
                "UPDATE cron_dlq SET status='resolved', resolved_at=?, resolved_by=? "
                "WHERE id=? AND status='pending'",
                (now, resolved_by, dlq_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def dlq_count(self) -> int:
        """Count of pending DLQ entries."""
        with self._lock:
            conn = self._ensure_conn()
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM cron_dlq WHERE status='pending'"
            ).fetchone()
            return row["cnt"] if row else 0

    # ── Maintenance ─────────────────────────────────────────────

    def cleanup(self, days: int = 30) -> int:
        """Remove old execution records and resolved DLQ entries.

        Returns total number of deleted rows (executions + DLQ).
        """
        with self._lock:
            conn = self._ensure_conn()
            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
            exec_cursor = conn.execute(
                "DELETE FROM cron_executions WHERE started_at < ?", (cutoff,)
            )
            dlq_cursor = conn.execute(
                "DELETE FROM cron_dlq WHERE status='resolved' AND resolved_at < ?",
                (cutoff,),
            )
            conn.commit()
            count = exec_cursor.rowcount + dlq_cursor.rowcount
            if count:
                logger.info(f"CronHistory: cleaned {count} records older than {days}d")
            return count

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> CronHistory:
        self.init()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    async def __aenter__(self) -> CronHistory:
        import asyncio

        await asyncio.to_thread(self.init)
        return self

    async def __aexit__(self, *exc: object) -> None:
        import asyncio

        await asyncio.to_thread(self.close)

    # ── Formatting ──────────────────────────────────────────────

    def format_runs(self, job_id: str | None = None, limit: int = 10) -> str:
        runs = self.get_runs(job_id, limit)
        if not runs:
            return "Немає записів виконання."
        lines = ["Історія виконання cron jobs:"]
        for r in runs:
            icon = {"success": "✅", "failed": "❌", "running": "⏳"}.get(r["status"], "?")
            started = r["started_at"][:19].replace("T", " ")
            dur = f" ({r['duration_sec']}s)" if r.get("duration_sec") else ""
            line = f"  {icon} {r['job_name']} — {started}{dur}"
            if r["error"]:
                line += f" | {r['error'][:60]}"
            lines.append(line)
        return "\n".join(lines)

    def format_dlq(self) -> str:
        entries = self.get_dlq()
        if not entries:
            return "DLQ порожній."
        lines = [f"Dead Letter Queue ({len(entries)} pending):"]
        for e in entries:
            created = e["created_at"][:19].replace("T", " ")
            lines.append(
                f"  #{e['id']} {e['job_name']} — {e['error'][:60]} "
                f"({e['attempts']} attempts, {created})"
            )
        return "\n".join(lines)
