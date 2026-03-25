"""PosipakScheduler — APScheduler wrapper for cron, reminders, intervals."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

if TYPE_CHECKING:
    from posipaka.core.cron_engine import CronEngine
    from posipaka.core.cron_executor import CronExecutor
    from posipaka.core.cron_history import CronHistory

# Misfire grace time per policy
_MISFIRE_GRACE: dict[str, int | None] = {
    "skip": 1,  # 1 second — effectively skip
    "fire_once": 3600,  # 1 hour window to catch up once
    "fire_all": None,  # unlimited — run all missed
}


class PosipakScheduler:
    """Unified scheduler for cron jobs, reminders and heartbeat."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._registered_engines: set[int] = set()  # id(cron_engine)

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Scheduler started")

    def stop(self, wait: bool = True) -> None:
        """Stop scheduler. If *wait*, block until running jobs finish."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)
            logger.info("Scheduler stopped")

    def add_reminder(
        self,
        job_id: str,
        callback: Callable[..., Awaitable[Any]],
        run_time: str,
        **kwargs: Any,
    ) -> None:
        """Add a one-shot reminder at *run_time* (ISO datetime)."""
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
        callback: Callable[..., Awaitable[Any]],
        cron_expression: str | None = None,
        hour: int | None = None,
        minute: int | None = None,
        timezone: str | None = None,
        misfire_grace_time: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Add a cron-triggered job."""
        if cron_expression:
            parts = cron_expression.split()
            trigger = CronTrigger(
                minute=parts[0] if len(parts) > 0 else "*",
                hour=parts[1] if len(parts) > 1 else "*",
                day=parts[2] if len(parts) > 2 else "*",
                month=parts[3] if len(parts) > 3 else "*",
                day_of_week=parts[4] if len(parts) > 4 else "*",
                timezone=timezone,
            )
        else:
            trigger = CronTrigger(
                hour=hour,
                minute=minute,
                timezone=timezone,
            )

        self._scheduler.add_job(
            callback,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            misfire_grace_time=misfire_grace_time,
            kwargs=kwargs,
        )
        logger.debug(f"Cron job added: {job_id}")

    def add_interval(
        self,
        job_id: str,
        callback: Callable[..., Awaitable[Any]],
        seconds: int,
        misfire_grace_time: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Add an interval-triggered job."""
        self._scheduler.add_job(
            callback,
            trigger=IntervalTrigger(seconds=seconds),
            id=job_id,
            replace_existing=True,
            misfire_grace_time=misfire_grace_time,
            kwargs=kwargs,
        )
        logger.debug(f"Interval job added: {job_id} every {seconds}s")

    def remove_job(self, job_id: str) -> bool:
        try:
            self._scheduler.remove_job(job_id)
            return True
        except Exception:
            return False

    def list_jobs(self) -> list[dict[str, Any]]:
        """List all scheduled jobs."""
        return [
            {
                "id": job.id,
                "next_run": (str(job.next_run_time) if job.next_run_time else None),
                "trigger": str(job.trigger),
            }
            for job in self._scheduler.get_jobs()
        ]

    def register_cron_jobs(
        self,
        cron_engine: CronEngine,
        executor: CronExecutor,
        agent_fn_provider: Callable[[], Callable[..., Awaitable[str]] | None] | None = None,
    ) -> int:
        """Auto-register all enabled CronEngine jobs in APScheduler.

        *agent_fn_provider* is a callable that returns the current agent_fn
        at execution time (not registration time), avoiding stale closures.

        Returns count of registered jobs.
        """
        from posipaka.core.cron_engine import CronEngine, CronJob, CronType

        count = 0
        for job_dict in cron_engine.list_jobs():
            if not job_dict["enabled"]:
                continue

            job = cron_engine.get(job_dict["id"])
            if not job:
                continue

            sched_id = f"cron:{job.id}"
            misfire = _MISFIRE_GRACE.get(job.misfire_policy, 3600)

            # Resolve agent_fn at call time via provider
            async def _run_job(
                j: CronJob = job,
                provider: Callable[[], Callable[..., Awaitable[str]] | None]
                | None = agent_fn_provider,
            ) -> None:
                fn = provider() if provider else None
                await executor.execute_job(j, agent_fn=fn)

            try:
                if job.type == CronType.ONE_SHOT and job.at:
                    self.add_reminder(
                        sched_id,
                        _run_job,
                        run_time=job.at,
                    )
                    count += 1
                elif job.cron:
                    self.add_cron(
                        sched_id,
                        _run_job,
                        cron_expression=job.cron,
                        timezone=job.timezone,
                        misfire_grace_time=misfire,
                    )
                    count += 1
                elif job.every:
                    seconds = CronEngine.parse_every(job.every)
                    self.add_interval(
                        sched_id,
                        _run_job,
                        seconds=seconds,
                        misfire_grace_time=misfire,
                    )
                    count += 1
            except Exception as e:
                logger.error(f"Failed to register job '{job.name}': {e}")

        # Update next_run_at for all registered jobs
        self._sync_next_run_times(cron_engine)

        # Register remove callback for APScheduler sync (once per engine)
        engine_id = id(cron_engine)
        if engine_id not in self._registered_engines:
            cron_engine.on_remove(lambda jid: self.remove_job(f"cron:{jid}"))
            self._registered_engines.add(engine_id)

        logger.info(f"Registered {count} cron jobs in scheduler")
        return count

    def _sync_next_run_times(self, cron_engine: CronEngine) -> None:
        """Update next_run_at for all jobs from APScheduler state."""
        for apjob in self._scheduler.get_jobs():
            if not apjob.id.startswith("cron:"):
                continue
            job_id = apjob.id[5:]  # strip "cron:" prefix
            try:
                next_run = getattr(apjob, "next_run_time", None)
                if next_run:
                    cron_engine.update_next_run(job_id, next_run.isoformat())
            except Exception as e:
                logger.debug(f"Cannot sync next_run for {apjob.id}: {e}")

    def register_history_cleanup(
        self,
        history: CronHistory,
        interval_hours: int = 24,
        retention_days: int = 30,
    ) -> None:
        """Register periodic CronHistory cleanup job."""
        from posipaka.core.cron_history import CronHistory as _CronHistory

        if not isinstance(history, _CronHistory):
            return

        async def _cleanup() -> None:
            import asyncio

            await asyncio.to_thread(history.cleanup, retention_days)

        self._scheduler.add_job(
            _cleanup,
            trigger=IntervalTrigger(hours=interval_hours),
            id="__cron_history_cleanup__",
            replace_existing=True,
        )
        logger.debug(
            f"History cleanup registered: every {interval_hours}h, retain {retention_days}d"
        )

    @property
    def running(self) -> bool:
        return bool(self._scheduler.running)
