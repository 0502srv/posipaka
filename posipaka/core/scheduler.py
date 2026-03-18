"""PosipakScheduler — APScheduler для cron завдань та нагадувань."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from loguru import logger


class PosipakScheduler:
    """Scheduler для cron завдань, нагадувань та heartbeat."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Scheduler started")

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    def add_reminder(
        self,
        job_id: str,
        callback: Callable,
        run_time: str,
        **kwargs: Any,
    ) -> None:
        """Додати одноразове нагадування."""
        self._scheduler.add_job(
            callback,
            trigger=DateTrigger(run_date=run_time),
            id=job_id,
            replace_existing=True,
            kwargs=kwargs,
        )
        logger.debug(f"Reminder added: {job_id} at {run_time}")

    def add_cron(
        self,
        job_id: str,
        callback: Callable,
        cron_expression: str | None = None,
        hour: int | None = None,
        minute: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Додати cron завдання."""
        if cron_expression:
            parts = cron_expression.split()
            trigger = CronTrigger(
                minute=parts[0] if len(parts) > 0 else "*",
                hour=parts[1] if len(parts) > 1 else "*",
                day=parts[2] if len(parts) > 2 else "*",
                month=parts[3] if len(parts) > 3 else "*",
                day_of_week=parts[4] if len(parts) > 4 else "*",
            )
        else:
            trigger = CronTrigger(hour=hour, minute=minute)

        self._scheduler.add_job(
            callback,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            kwargs=kwargs,
        )
        logger.debug(f"Cron job added: {job_id}")

    def remove_job(self, job_id: str) -> bool:
        """Видалити завдання."""
        try:
            self._scheduler.remove_job(job_id)
            return True
        except Exception:
            return False

    def list_jobs(self) -> list[dict]:
        """Список активних завдань."""
        jobs = self._scheduler.get_jobs()
        return [
            {
                "id": job.id,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
            for job in jobs
        ]
