"""CronEngine — persistent cron jobs with 4 types and schedule validation."""

from __future__ import annotations

import json
import random
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from loguru import logger

__all__ = [
    "CronEngine",
    "CronJob",
    "CronType",
    "DeliveryMode",
    "MisfirePolicy",
    "SessionMode",
]

_JOB_ID_LENGTH = 12
_JITTER_FACTOR = 0.2
_MAX_JOBS = 200
_DEFAULT_TIMEOUT_SECONDS = 300  # 5 min
_DEFAULT_AUTO_DISABLE_AFTER = 10  # consecutive failures before auto-disable
_READONLY_FIELDS = frozenset(
    {
        "id",
        "run_count",
        "consecutive_failures",
        "last_run",
        "last_error",
        "updated_at",
    }
)


class CronType(StrEnum):
    ONE_SHOT = "one_shot"
    RECURRING = "recurring"
    INTERVAL = "interval"
    WORKFLOW = "workflow"


class DeliveryMode(StrEnum):
    ANNOUNCE = "announce"
    WEBHOOK = "webhook"
    NONE = "none"


class MisfirePolicy(StrEnum):
    SKIP = "skip"
    FIRE_ONCE = "fire_once"
    FIRE_ALL = "fire_all"


class SessionMode(StrEnum):
    ISOLATED = "isolated"
    MAIN = "main"
    CURRENT = "current"
    CUSTOM = "custom"


@dataclass
class CronJob:
    """Persistent cron job definition."""

    id: str
    name: str
    type: str
    message: str
    user_id: str
    channel: str = "telegram"

    # Schedule (one of these)
    at: str = ""
    cron: str = ""
    every: str = ""

    # Delivery
    target_channel: str = ""
    target_user_id: str = ""
    delivery_mode: str = DeliveryMode.ANNOUNCE
    webhook_url: str = ""

    # Options
    session_mode: str = SessionMode.ISOLATED
    session_name: str = ""
    model: str = ""
    announce: bool = True
    delete_after_run: bool = False
    enabled: bool = True
    timezone: str = "Europe/Kyiv"
    max_retries: int = 0
    retry_delay_seconds: int = 60
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS
    misfire_policy: str = MisfirePolicy.FIRE_ONCE
    workflow_name: str = ""
    auto_disable_after: int = _DEFAULT_AUTO_DISABLE_AFTER

    # State
    last_run: str = ""
    next_run_at: str = ""
    run_count: int = 0
    last_error: str = ""
    consecutive_failures: int = 0
    updated_at: str = ""

    @property
    def effective_channel(self) -> str:
        return self.target_channel or self.channel

    @property
    def effective_user(self) -> str:
        return self.target_user_id or self.user_id

    @property
    def effective_delivery(self) -> str:
        if self.delivery_mode:
            return self.delivery_mode
        return DeliveryMode.ANNOUNCE if self.announce else DeliveryMode.NONE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CronJob:
        known = cls.__dataclass_fields__
        unknown = set(data) - set(known)
        if unknown:
            logger.debug(f"CronJob.from_dict: ignoring unknown fields: {unknown}")
        filtered = {k: v for k, v in data.items() if k in known}
        _validate_enum_fields(filtered)
        return cls(**filtered)


_ENUM_VALIDATORS: dict[str, type[StrEnum]] = {
    "type": CronType,
    "delivery_mode": DeliveryMode,
    "session_mode": SessionMode,
    "misfire_policy": MisfirePolicy,
}


def _validate_enum_fields(data: dict[str, Any]) -> None:
    """Validate that enum-typed fields contain valid values."""
    for field, enum_cls in _ENUM_VALIDATORS.items():
        value = data.get(field)
        if value and value not in {e.value for e in enum_cls}:
            valid = ", ".join(e.value for e in enum_cls)
            raise ValueError(f"Invalid {field}={value!r} — expected one of: {valid}")


def _validate_webhook_url(url: str) -> None:
    """Basic webhook URL format validation (scheme + host)."""
    if not url:
        return
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"webhook_url must use http/https scheme, got {parsed.scheme!r}")
    if not parsed.netloc:
        raise ValueError("webhook_url must have a valid host")


class CronEngine:
    """Persistent cron engine.

    Jobs stored in ``~/.posipaka/cron/{id}.json``.
    Auto-recovery on restart.
    """

    def __init__(
        self,
        cron_dir: Path,
        *,
        max_jobs: int = _MAX_JOBS,
    ) -> None:
        self._cron_dir = cron_dir
        self._max_jobs = max_jobs
        self._jobs: dict[str, CronJob] = {}
        self._name_index: dict[str, str] = {}  # name → job_id
        self._on_remove_callbacks: list[Callable[[str], None]] = []

    def on_remove(self, callback: Callable[[str], None]) -> None:
        """Register callback invoked with job_id when a job is removed."""
        self._on_remove_callbacks.append(callback)

    def init(self) -> None:
        """Load all jobs from disk."""
        self._cron_dir.mkdir(parents=True, exist_ok=True)
        for f in self._cron_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                job = CronJob.from_dict(data)
                self._jobs[job.id] = job
                self._name_index[job.name] = job.id
            except Exception as e:
                logger.warning(f"Error loading cron job {f}: {e}")
        logger.info(f"Loaded {len(self._jobs)} cron jobs")

    def add(
        self,
        name: str,
        message: str,
        user_id: str,
        cron_type: CronType = CronType.RECURRING,
        at: str = "",
        cron: str = "",
        every: str = "",
        channel: str = "telegram",
        session_mode: SessionMode = SessionMode.ISOLATED,
        session_name: str = "",
        model: str = "",
        announce: bool = True,
        delete_after_run: bool = False,
        timezone: str = "Europe/Kyiv",
        target_channel: str = "",
        target_user_id: str = "",
        delivery_mode: str = DeliveryMode.ANNOUNCE,
        webhook_url: str = "",
        max_retries: int = 0,
        retry_delay_seconds: int = 60,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
        misfire_policy: str = MisfirePolicy.FIRE_ONCE,
        workflow_name: str = "",
        auto_disable_after: int = _DEFAULT_AUTO_DISABLE_AFTER,
    ) -> CronJob:
        """Create a new cron job with schedule validation."""
        if len(self._jobs) >= self._max_jobs:
            raise ValueError(
                f"Maximum number of cron jobs ({self._max_jobs}) reached. "
                f"Remove unused jobs before adding new ones."
            )
        if name in self._name_index:
            raise ValueError(f"Job with name '{name}' already exists (id={self._name_index[name]})")
        self._validate_schedule(cron_type, at=at, cron=cron, every=every)
        _validate_webhook_url(webhook_url)
        _validate_enum_fields(
            {
                "type": cron_type,
                "delivery_mode": delivery_mode,
                "session_mode": session_mode,
                "misfire_policy": misfire_policy,
            }
        )
        job_id = self._generate_unique_id()
        job = CronJob(
            id=job_id,
            name=name,
            type=cron_type,
            message=message,
            user_id=user_id,
            channel=channel,
            at=at,
            cron=cron,
            every=every,
            target_channel=target_channel,
            target_user_id=target_user_id,
            delivery_mode=delivery_mode,
            webhook_url=webhook_url,
            session_mode=session_mode,
            session_name=session_name,
            model=model,
            announce=announce,
            delete_after_run=delete_after_run,
            timezone=timezone,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            timeout_seconds=timeout_seconds,
            misfire_policy=misfire_policy,
            workflow_name=workflow_name,
            auto_disable_after=auto_disable_after,
        )
        self._jobs[job.id] = job
        self._name_index[job.name] = job.id
        self._save(job)
        logger.info(f"Cron job added: {job.name} ({job.type})")
        return job

    def remove(self, job_id: str) -> bool:
        """Remove job by ID or name. Notifies on_remove callbacks."""
        # Resolve name → id via index
        resolved_id = self._name_index.get(job_id) or job_id
        job = self._jobs.pop(resolved_id, None)
        if not job:
            return False
        self._name_index.pop(job.name, None)
        self._delete_file(resolved_id)
        self._notify_removed(resolved_id)
        return True

    def get(self, job_id: str) -> CronJob | None:
        """Get job by ID or name. O(1) lookup via name index."""
        job = self._jobs.get(job_id)
        if job:
            return job
        resolved_id = self._name_index.get(job_id)
        if resolved_id:
            return self._jobs.get(resolved_id)
        return None

    def enable(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job:
            job.enabled = True
            self._save(job)
            return True
        return False

    def disable(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job:
            job.enabled = False
            self._save(job)
            return True
        return False

    def update(self, job_id: str, **fields: Any) -> CronJob:
        """Update job fields with validation. Raises ValueError on bad input."""
        job = self.get(job_id)
        if not job:
            raise ValueError(f"Job '{job_id}' not found")

        bad = set(fields) & _READONLY_FIELDS
        if bad:
            raise ValueError(f"Cannot update readonly fields: {bad}")

        unknown = set(fields) - set(CronJob.__dataclass_fields__)
        if unknown:
            raise ValueError(f"Unknown fields: {unknown}")

        # Validate enum fields if any are being updated
        enum_update = {k: fields[k] for k in _ENUM_VALIDATORS if k in fields}
        if enum_update:
            _validate_enum_fields(enum_update)

        # Validate webhook URL if being updated
        if "webhook_url" in fields:
            _validate_webhook_url(fields["webhook_url"])

        # Re-validate schedule if schedule fields change
        new_at = fields.get("at", job.at)
        new_cron = fields.get("cron", job.cron)
        new_every = fields.get("every", job.every)
        new_type = fields.get("type", job.type)
        if {"at", "cron", "every", "type"} & set(fields):
            self._validate_schedule(
                new_type,
                at=new_at,
                cron=new_cron,
                every=new_every,
            )

        # Validate name uniqueness on rename
        new_name = fields.get("name")
        if new_name and new_name != job.name:
            if new_name in self._name_index:
                raise ValueError(f"Job with name '{new_name}' already exists")
            self._name_index.pop(job.name, None)

        old_name = job.name
        for key, value in fields.items():
            setattr(job, key, value)

        # Update name index
        if new_name and new_name != old_name:
            self._name_index[new_name] = job.id

        self._save(job)
        logger.info(f"Cron job updated: {job.name} ({', '.join(fields)})")
        return job

    def mark_run(self, job_id: str) -> None:
        """Mark job as successfully executed."""
        job = self._jobs.get(job_id)
        if not job:
            return
        job.last_run = datetime.now(UTC).isoformat()
        job.run_count += 1
        job.last_error = ""
        job.consecutive_failures = 0
        if job.delete_after_run:
            self.remove(job_id)
        else:
            self._save(job)

    def mark_error(self, job_id: str, error: str) -> None:
        """Mark execution failure. Auto-disables after threshold."""
        job = self._jobs.get(job_id)
        if not job:
            return
        job.last_error = error
        job.consecutive_failures += 1

        # Circuit breaker: auto-disable after N consecutive failures
        if (
            job.auto_disable_after > 0
            and job.consecutive_failures >= job.auto_disable_after
            and job.enabled
        ):
            job.enabled = False
            logger.warning(
                f"Job '{job.name}' auto-disabled after "
                f"{job.consecutive_failures} consecutive failures"
            )

        self._save(job)

    def should_retry(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        return job.max_retries > 0 and job.consecutive_failures <= job.max_retries

    def get_retry_delay(self, job_id: str) -> float:
        """Exponential backoff delay with jitter (seconds). Capped at 1 hour."""
        job = self._jobs.get(job_id)
        if not job:
            return 0
        exponent = min(job.consecutive_failures - 1, 10)
        base = job.retry_delay_seconds * (2**exponent)
        base = min(base, 3600)  # cap at 1 hour
        jitter = random.uniform(0, base * _JITTER_FACTOR)  # noqa: S311
        return float(base + jitter)

    def list_jobs(
        self,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all jobs, optionally filtered by user."""
        jobs: list[CronJob] = list(self._jobs.values())
        if user_id:
            jobs = [j for j in jobs if j.user_id == user_id]
        return [
            {
                "id": j.id,
                "name": j.name,
                "type": j.type,
                "enabled": j.enabled,
                "message": j.message[:50],
                "schedule": j.cron or j.every or j.at,
                "last_run": j.last_run,
                "run_count": j.run_count,
                "delivery": j.effective_delivery,
                "target": f"{j.effective_channel}:{j.effective_user}",
                "last_error": j.last_error,
            }
            for j in jobs
        ]

    def update_next_run(self, job_id: str, next_run_at: str) -> None:
        """Update next_run_at for a job (called by scheduler)."""
        job = self._jobs.get(job_id)
        if job:
            job.next_run_at = next_run_at
            self._save(job)

    # ── Persistence ─────────────────────────────────────────────

    def _generate_unique_id(self) -> str:
        """Generate collision-free job ID."""
        for _ in range(100):
            job_id = str(uuid.uuid4())[:_JOB_ID_LENGTH]
            if job_id not in self._jobs:
                return job_id
        return str(uuid.uuid4())

    def _notify_removed(self, job_id: str) -> None:
        """Notify all on_remove callbacks (e.g. APScheduler sync)."""
        for cb in self._on_remove_callbacks:
            try:
                cb(job_id)
            except Exception as e:
                logger.debug(f"on_remove callback error: {e}")

    def _save(self, job: CronJob) -> None:
        job.updated_at = datetime.now(UTC).isoformat()
        path = self._cron_dir / f"{job.id}.json"
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(job.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.rename(path)  # atomic on POSIX

    def _delete_file(self, job_id: str) -> None:
        path = self._cron_dir / f"{job_id}.json"
        path.unlink(missing_ok=True)

    # ── Workflow registration ───────────────────────────────────

    def register_workflow(
        self,
        workflow_name: str,
        cron_expression: str,
        user_id: str,
        channel: str = "telegram",
        **kwargs: Any,
    ) -> CronJob:
        """Register a workflow as a cron job (idempotent)."""
        existing = self.get(f"workflow:{workflow_name}")
        if existing:
            return existing

        return self.add(
            name=f"workflow:{workflow_name}",
            message=f"Execute workflow: {workflow_name}",
            user_id=user_id,
            cron_type=CronType.WORKFLOW,
            cron=cron_expression,
            channel=channel,
            workflow_name=workflow_name,
            **kwargs,
        )

    # ── Validation ──────────────────────────────────────────────

    @staticmethod
    def _validate_schedule(
        cron_type: str | CronType,
        *,
        at: str = "",
        cron: str = "",
        every: str = "",
    ) -> None:
        """Validate schedule params before persisting."""
        # Mutual exclusivity: exactly one schedule field
        fields_set = sum(bool(f) for f in (at, cron, every))
        if cron_type != CronType.WORKFLOW and fields_set == 0:
            raise ValueError("Schedule required: set one of (at, cron, every)")
        if cron_type != CronType.WORKFLOW and fields_set > 1:
            raise ValueError("Only one of (at, cron, every) can be set")

        if cron_type == CronType.ONE_SHOT and at:
            try:
                datetime.fromisoformat(at)
            except ValueError as e:
                raise ValueError(f"Invalid 'at' datetime: {at!r}") from e

        if cron_type == CronType.RECURRING and cron:
            parts = cron.strip().split()
            if len(parts) != 5:
                raise ValueError(
                    f"Invalid cron expression: {cron!r} — expected 5 fields, got {len(parts)}"
                )
            try:
                from apscheduler.triggers.cron import CronTrigger

                CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                )
            except (ValueError, KeyError) as e:
                raise ValueError(f"Invalid cron expression: {cron!r} — {e}") from e

        if cron_type == CronType.INTERVAL and every:
            try:
                CronEngine.parse_every(every)
            except (ValueError, IndexError) as e:
                raise ValueError(f"Invalid 'every' interval: {every!r}") from e

    @staticmethod
    def parse_every(every: str) -> int:
        """Parse '30m', '4h', '1d', '60s' to seconds."""
        every = every.strip().lower()
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        for suffix, mult in multipliers.items():
            if every.endswith(suffix):
                value = int(every[: -len(suffix)])
                if value <= 0:
                    raise ValueError(f"Interval must be positive: {every}")
                return value * mult
        # No suffix — treat as minutes
        value = int(every)
        if value <= 0:
            raise ValueError(f"Interval must be positive: {every}")
        return value * 60
