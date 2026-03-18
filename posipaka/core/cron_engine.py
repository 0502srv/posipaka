"""CronEngine — persistent cron jobs з 3 типами (секція 53 MASTER.md)."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC
from enum import StrEnum
from pathlib import Path

from loguru import logger


class CronType(StrEnum):
    ONE_SHOT = "one_shot"  # --at: одноразово
    RECURRING = "recurring"  # --cron: UNIX cron expression
    INTERVAL = "interval"  # --every: кожні N хвилин


class SessionMode(StrEnum):
    ISOLATED = "isolated"  # окрема сесія (для звітів)
    MAIN = "main"  # основна сесія (для нагадувань)


@dataclass
class CronJob:
    id: str
    name: str
    type: str  # CronType value
    message: str
    user_id: str
    channel: str = "telegram"

    # Schedule (one of these)
    at: str = ""  # ISO datetime for one_shot
    cron: str = ""  # "0 9 * * *" for recurring
    every: str = ""  # "30m", "4h" for interval

    # Options
    session_mode: str = "isolated"  # SessionMode
    model: str = ""  # override model for this job
    announce: bool = True  # send result to user
    delete_after_run: bool = False  # for one-shot
    enabled: bool = True
    timezone: str = "Europe/Kyiv"

    # State
    last_run: str = ""
    run_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> CronJob:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class CronEngine:
    """
    Persistent cron engine.

    Jobs зберігаються в ~/.posipaka/cron/{id}.json.
    При перезапуску — автоматичне відновлення.
    """

    def __init__(self, cron_dir: Path) -> None:
        self._cron_dir = cron_dir
        self._jobs: dict[str, CronJob] = {}

    def init(self) -> None:
        """Завантажити всі jobs з диску."""
        self._cron_dir.mkdir(parents=True, exist_ok=True)
        for f in self._cron_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                job = CronJob.from_dict(data)
                self._jobs[job.id] = job
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
        model: str = "",
        announce: bool = True,
        delete_after_run: bool = False,
        timezone: str = "Europe/Kyiv",
    ) -> CronJob:
        """Створити новий cron job."""
        job = CronJob(
            id=str(uuid.uuid4())[:8],
            name=name,
            type=cron_type,
            message=message,
            user_id=user_id,
            channel=channel,
            at=at,
            cron=cron,
            every=every,
            session_mode=session_mode,
            model=model,
            announce=announce,
            delete_after_run=delete_after_run,
            timezone=timezone,
        )
        self._jobs[job.id] = job
        self._save(job)
        logger.info(f"Cron job added: {job.name} ({job.type})")
        return job

    def remove(self, job_id: str) -> bool:
        """Видалити job."""
        job = self._jobs.pop(job_id, None)
        if not job:
            # Try by name
            for jid, j in list(self._jobs.items()):
                if j.name == job_id:
                    self._jobs.pop(jid)
                    self._delete_file(jid)
                    return True
            return False
        self._delete_file(job_id)
        return True

    def get(self, job_id: str) -> CronJob | None:
        job = self._jobs.get(job_id)
        if job:
            return job
        # Search by name
        for j in self._jobs.values():
            if j.name == job_id:
                return j
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

    def mark_run(self, job_id: str) -> None:
        """Позначити що job виконано."""
        from datetime import datetime

        job = self._jobs.get(job_id)
        if not job:
            return
        job.last_run = datetime.now(UTC).isoformat()
        job.run_count += 1
        if job.delete_after_run:
            self.remove(job_id)
        else:
            self._save(job)

    def list_jobs(self) -> list[dict]:
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
            }
            for j in self._jobs.values()
        ]

    def _save(self, job: CronJob) -> None:
        path = self._cron_dir / f"{job.id}.json"
        path.write_text(
            json.dumps(job.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _delete_file(self, job_id: str) -> None:
        path = self._cron_dir / f"{job_id}.json"
        path.unlink(missing_ok=True)

    @staticmethod
    def parse_every(every: str) -> int:
        """Parse '30m', '4h', '1d' → seconds."""
        every = every.strip().lower()
        if every.endswith("m"):
            return int(every[:-1]) * 60
        if every.endswith("h"):
            return int(every[:-1]) * 3600
        if every.endswith("d"):
            return int(every[:-1]) * 86400
        return int(every) * 60  # default minutes
