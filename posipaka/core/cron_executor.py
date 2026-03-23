"""CronExecutor — orchestrates cron job lifecycle with infrastructure integration.

Architecture::

    CronEngine (data) -> CronExecutor (orchestration) -> Delivery
                            |                |              |
                     DegradationMgr    CostGuard    Gateway/Webhook
                     HookManager      SLOMonitor
                                      CronHistory

Key guarantees:
    - Idempotent: same job won't run twice concurrently (lock per job_id)
    - Backpressure: configurable max_concurrent_jobs via semaphore
    - Dead letter: exhausted retries land in DLQ for manual inspection
    - Observable: hooks emitted for every lifecycle transition
    - Degradation-aware: skips execution in EMERGENCY/MINIMAL modes
    - Cost-aware: respects CostGuard budget before LLM calls
    - Timeout: per-job execution timeout prevents slot starvation
    - SSRF-safe: webhook URLs validated against internal IP ranges
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from posipaka.core.cron_engine import CronJob, CronType, DeliveryMode, SessionMode

if TYPE_CHECKING:
    from posipaka.core.cost_guard import CostGuard
    from posipaka.core.cron_engine import CronEngine
    from posipaka.core.cron_history import CronHistory
    from posipaka.core.degradation import DegradationManager
    from posipaka.core.gateway import MessageGateway
    from posipaka.core.hooks.manager import HookManager
    from posipaka.core.quality import SLOMonitor
    from posipaka.core.workflow import WorkflowEngine

# Type alias for the agent callback
AgentFn = Callable[..., Awaitable[str]]

__all__ = ["CronExecutor", "CronBudgetExceededError"]

_WEBHOOK_TIMEOUT_SECONDS = 30
_WEBHOOK_MAX_RETRIES = 2
_SHUTDOWN_POLL_INTERVAL = 0.5
_MAX_LOCKS = 500


class CronExecutor:
    """Orchestrates cron job execution with full infrastructure integration."""

    DEFAULT_MAX_CONCURRENT = 5
    DEFAULT_SHUTDOWN_TIMEOUT = 30.0

    def __init__(
        self,
        cron_engine: CronEngine,
        gateway: MessageGateway | None = None,
        history: CronHistory | None = None,
        workflow_engine: WorkflowEngine | None = None,
        hooks: HookManager | None = None,
        degradation: DegradationManager | None = None,
        cost_guard: CostGuard | None = None,
        slo_monitor: SLOMonitor | None = None,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        gateway_provider: Callable[[], MessageGateway | None] | None = None,
    ) -> None:
        self._engine = cron_engine
        self._gateway = gateway
        self._gateway_provider = gateway_provider
        self._history = history
        self._workflow_engine = workflow_engine
        self._hooks = hooks
        self._degradation = degradation
        self._cost_guard = cost_guard
        self._slo_monitor = slo_monitor

        # Concurrency control
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._running_jobs: dict[str, float] = {}
        self._webhook_tasks: set[asyncio.Task[None]] = set()
        self._webhook_session: Any = None  # lazy aiohttp.ClientSession

    def _get_gateway(self) -> MessageGateway | None:
        """Resolve gateway lazily to handle init-order dependency."""
        if self._gateway:
            return self._gateway
        if self._gateway_provider:
            self._gateway = self._gateway_provider()
        return self._gateway

    # ── Public API ──────────────────────────────────────────────

    async def execute_job(
        self,
        job: CronJob,
        agent_fn: AgentFn | None = None,
    ) -> str | None:
        """Execute a single cron job with all safety guarantees."""
        if not job.enabled:
            return None

        if not self._check_system_mode(job):
            return None

        lock = self._get_lock(job.id)
        if lock.locked():
            logger.warning(f"Job '{job.name}' already running, skip")
            return None

        async with self._semaphore, lock:
            return await self._execute_with_lifecycle(job, agent_fn)

    async def execute_all_enabled(
        self, agent_fn: AgentFn | None = None,
    ) -> list[str]:
        """Execute all enabled jobs. Returns IDs of successful jobs."""
        enabled_jobs = [
            job
            for j in self._engine.list_jobs()
            if j["enabled"] and (job := self._engine.get(j["id"]))
        ]
        tasks = [self.execute_job(job, agent_fn) for job in enabled_jobs]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [
            job.id
            for job, result in zip(enabled_jobs, results)
            if result is not None and not isinstance(result, Exception)
        ]

    async def graceful_shutdown(
        self, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> None:
        """Wait for running jobs to complete or timeout."""
        if not self._running_jobs:
            return

        logger.info(
            f"Cron shutdown: waiting for {len(self._running_jobs)} jobs..."
        )
        deadline = time.monotonic() + timeout
        while self._running_jobs and time.monotonic() < deadline:
            await asyncio.sleep(_SHUTDOWN_POLL_INTERVAL)

        if self._running_jobs:
            orphaned = list(self._running_jobs.keys())
            logger.warning(f"Cron shutdown timeout: {orphaned} orphaned")
        else:
            logger.info("Cron shutdown: all jobs completed")

        await self._close_webhook_session()

    async def close(self) -> None:
        """Release resources. Safe to call multiple times."""
        await self._close_webhook_session()
        # Cancel any in-flight webhook tasks
        for task in list(self._webhook_tasks):
            task.cancel()
        self._webhook_tasks.clear()

    @property
    def running_jobs(self) -> dict[str, float]:
        """Currently running jobs: ``{job_id: start_timestamp}``."""
        return dict(self._running_jobs)

    @property
    def concurrency_available(self) -> int:
        """Remaining concurrency slots."""
        return self._max_concurrent - len(self._running_jobs)

    # ── Lifecycle ───────────────────────────────────────────────

    async def _execute_with_lifecycle(
        self, job: CronJob, agent_fn: AgentFn | None,
    ) -> str | None:
        """Full lifecycle: hooks -> execute -> metrics -> deliver."""
        start_ts = time.monotonic()
        self._running_jobs[job.id] = time.time()

        exec_id = None
        if self._history:
            exec_id = await asyncio.to_thread(
                self._history.record_start, job.id, job.name,
            )

        await self._emit("job_triggered", {
            "job_id": job.id,
            "job_name": job.name,
            "job_type": job.type,
        })

        try:
            result = await self._run_with_retry(job, agent_fn)
            duration = time.monotonic() - start_ts

            self._engine.mark_run(job.id)
            if self._history and exec_id is not None:
                await asyncio.to_thread(
                    self._history.record_success,
                    exec_id, result or "",
                    delivery_mode=job.effective_delivery,
                    target_channel=job.effective_channel,
                    target_user_id=job.effective_user,
                    duration_sec=round(duration, 2),
                )
            self._record_metrics(job, duration, success=True)
            await self._emit("job_completed", {
                "job_id": job.id,
                "job_name": job.name,
                "duration_sec": round(duration, 2),
            })

            if result:
                await self._deliver(job, result)
            return result

        except _RetriesExhaustedError as e:
            duration = time.monotonic() - start_ts
            error_msg = str(e.original_error)

            if self._history and exec_id is not None:
                await asyncio.to_thread(
                    self._history.record_failure, exec_id, error_msg,
                )
                await asyncio.to_thread(
                    self._history.add_to_dlq,
                    job_id=job.id,
                    job_name=job.name,
                    error=error_msg,
                    attempts=job.max_retries + 1,
                )
            self._record_metrics(job, duration, success=False)
            await self._emit("job_failed", {
                "job_id": job.id,
                "job_name": job.name,
                "error": error_msg,
                "attempts": job.max_retries + 1,
            })

            await self._deliver_error(job, error_msg)
            return None

        finally:
            self._running_jobs.pop(job.id, None)
            if not self._engine.get(job.id):
                self._locks.pop(job.id, None)

    async def _run_with_retry(
        self, job: CronJob, agent_fn: AgentFn | None,
    ) -> str:
        """Execute with exponential backoff. Raises on exhaustion."""
        max_attempts = 1 + job.max_retries
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                return await self._run_once(job, agent_fn)
            except Exception as e:
                last_error = e
                self._engine.mark_error(job.id, str(e))
                logger.error(
                    f"Job '{job.name}' attempt "
                    f"{attempt + 1}/{max_attempts}: {e}"
                )
                if attempt + 1 < max_attempts:
                    delay = self._engine.get_retry_delay(job.id)
                    logger.info(f"Job '{job.name}' retry in {delay:.1f}s")
                    await asyncio.sleep(delay)

        raise _RetriesExhaustedError(last_error)

    async def _run_once(
        self, job: CronJob, agent_fn: AgentFn | None,
    ) -> str:
        """Single execution attempt with per-job timeout."""
        if job.type == CronType.WORKFLOW and job.workflow_name:
            return await asyncio.wait_for(
                self._run_workflow(job),
                timeout=job.timeout_seconds,
            )

        if not agent_fn:
            return f"[cron:{job.name}] No agent function configured"

        if self._cost_guard and job.type != CronType.WORKFLOW:
            allowed, reason = self._cost_guard.check_before_call(
                model=job.model or "default",
                estimated_input_tokens=(
                    self._cost_guard.estimate_tokens(job.message)
                ),
                session_id=f"cron:{job.id}",
            )
            if not allowed:
                raise CronBudgetExceededError(
                    f"Budget exceeded: {reason}"
                )

        session_id = self._resolve_session_id(job)
        result = await asyncio.wait_for(
            agent_fn(
                message=job.message,
                user_id=job.effective_user,
                session_mode=job.session_mode,
                session_name=job.session_name,
                session_id=session_id,
                model=job.model or None,
            ),
            timeout=job.timeout_seconds,
        )
        return result or ""

    async def _run_workflow(self, job: CronJob) -> str:
        """Execute a workflow job."""
        if not self._workflow_engine:
            raise RuntimeError(
                f"WorkflowEngine not available for '{job.workflow_name}'"
            )

        results = await self._workflow_engine.execute(
            name=job.workflow_name,
            tool_executor=None,
            llm_fn=None,
        )
        if "error" in results:
            raise RuntimeError(results["error"])

        successes = []
        errors = []
        for step_id, value in results.items():
            if isinstance(value, str) and value.startswith("ERROR:"):
                errors.append(f"[{step_id}] {value}")
            else:
                successes.append(str(value))

        if errors and not successes:
            raise RuntimeError(
                f"All workflow steps failed: {'; '.join(errors)}"
            )
        if errors:
            logger.warning(
                f"Workflow '{job.workflow_name}' partial failures: "
                f"{'; '.join(errors)}"
            )
        return "\n\n".join(successes) if successes else "Workflow completed"

    # ── Delivery ────────────────────────────────────────────────

    async def _deliver(self, job: CronJob, result: str) -> None:
        """Route result to the configured delivery channel."""
        mode = job.effective_delivery

        if mode == DeliveryMode.NONE:
            return
        if mode == DeliveryMode.WEBHOOK:
            await self._deliver_webhook(job, result)
            return
        await self._deliver_announce(job, result)

    async def _deliver_announce(
        self, job: CronJob, result: str,
    ) -> None:
        gateway = self._get_gateway()
        if not gateway:
            logger.warning(
                f"Job '{job.name}': no gateway for delivery"
            )
            return
        try:
            await gateway.send_to_channel(
                job.effective_channel, job.effective_user, result,
            )
        except Exception as e:
            logger.error(f"Job '{job.name}' delivery failed: {e}")

    async def _deliver_webhook(
        self, job: CronJob, result: str,
    ) -> None:
        if not job.webhook_url:
            logger.warning(f"Job '{job.name}': webhook_url not set")
            return

        # SSRF validation
        try:
            from posipaka.security.ssrf import validate_url

            safe, reason = validate_url(job.webhook_url)
            if not safe:
                logger.error(
                    f"Job '{job.name}' webhook blocked (SSRF): {reason}"
                )
                return
        except ImportError:
            pass

        # Fire-and-forget: don't block executor on slow webhooks
        task = asyncio.create_task(
            self._send_webhook(job, result),
            name=f"webhook:{job.id}",
        )
        self._webhook_tasks.add(task)
        task.add_done_callback(self._webhook_tasks.discard)

    async def _get_webhook_session(self) -> Any:
        """Lazy-init shared aiohttp session for webhooks."""
        if self._webhook_session is None or self._webhook_session.closed:
            try:
                import aiohttp  # type: ignore[import-not-found]
            except ImportError:
                return None
            self._webhook_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=_WEBHOOK_TIMEOUT_SECONDS),
            )
        return self._webhook_session

    async def _send_webhook(
        self, job: CronJob, result: str,
    ) -> None:
        """Actual webhook POST with retry (runs as background task)."""
        payload = {
            "job_id": job.id,
            "job_name": job.name,
            "result": result,
            "timestamp": datetime.now(UTC).isoformat(),
            "user_id": job.effective_user,
            "channel": job.effective_channel,
        }
        session = await self._get_webhook_session()
        if session is None:
            logger.error(
                f"Job '{job.name}': aiohttp required for webhook"
            )
            return

        for attempt in range(_WEBHOOK_MAX_RETRIES + 1):
            try:
                async with session.post(
                    job.webhook_url, json=payload,
                ) as resp:
                    if resp.status < 400:
                        logger.debug(
                            f"Job '{job.name}' webhook OK ({resp.status})"
                        )
                        return
                    logger.error(
                        f"Job '{job.name}' webhook HTTP {resp.status}"
                    )
            except Exception as e:
                logger.error(f"Job '{job.name}' webhook error: {e}")

            if attempt < _WEBHOOK_MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)

    async def _deliver_error(
        self, job: CronJob, error: str,
    ) -> None:
        if job.effective_delivery == DeliveryMode.NONE:
            return
        msg = (
            f"Cron job '{job.name}' failed after "
            f"{job.max_retries + 1} attempts:\n{error}"
        )
        await self._deliver(job, msg)

    # ── Infrastructure integration ──────────────────────────────

    def _check_system_mode(self, job: CronJob) -> bool:
        """Gate: skip jobs in EMERGENCY; skip workflows in MINIMAL."""
        if not self._degradation:
            return True
        mode = str(self._degradation.mode)
        if mode == "emergency":
            logger.warning(
                f"Job '{job.name}' skipped: EMERGENCY mode"
            )
            return False
        if mode == "minimal" and job.type == CronType.WORKFLOW:
            logger.warning(
                f"Workflow '{job.name}' skipped: MINIMAL mode"
            )
            return False
        return True

    def _record_metrics(
        self, job: CronJob, duration: float, *, success: bool,
    ) -> None:
        """Push metrics to SLOMonitor."""
        if not self._slo_monitor:
            return
        try:
            self._slo_monitor.record(
                "cron_job_duration", duration,
                job_id=job.id, job_type=job.type,
            )
            if not success:
                self._slo_monitor.record(
                    "cron_job_error", 1.0,
                    job_id=job.id, error=job.last_error,
                )
        except Exception as e:
            logger.debug(f"SLO record error: {e}")

    async def _emit(
        self, event_name: str, data: dict[str, Any],
    ) -> None:
        """Emit hook event with error isolation."""
        if not self._hooks:
            return
        try:
            from posipaka.core.hooks.manager import HookEvent

            # HookEvent is a StrEnum — values match names like "job_triggered"
            event = HookEvent(event_name)
            await self._hooks.emit(event, data)
        except ValueError:
            logger.debug(f"Hook event '{event_name}' not in HookEvent enum")
        except Exception as e:
            logger.debug(f"Hook emit '{event_name}': {e}")

    async def _close_webhook_session(self) -> None:
        """Close shared webhook session if open."""
        if self._webhook_session and not self._webhook_session.closed:
            await self._webhook_session.close()
            self._webhook_session = None

    # ── Helpers ─────────────────────────────────────────────────

    def _get_lock(self, job_id: str) -> asyncio.Lock:
        """Get or create per-job lock with LRU eviction to prevent memory leak."""
        if job_id in self._locks:
            self._locks.move_to_end(job_id)
            return self._locks[job_id]

        # Evict oldest unlocked entries when over limit
        while len(self._locks) >= _MAX_LOCKS:
            oldest_id, oldest_lock = next(iter(self._locks.items()))
            if oldest_lock.locked():
                break
            del self._locks[oldest_id]

        lock = asyncio.Lock()
        self._locks[job_id] = lock
        return lock

    @staticmethod
    def _resolve_session_id(job: CronJob) -> str:
        """Map session mode to a concrete session ID."""
        if job.session_mode == SessionMode.CUSTOM and job.session_name:
            return f"cron:custom:{job.session_name}"
        if job.session_mode == SessionMode.CURRENT:
            return f"cron:current:{job.id}"
        if job.session_mode == SessionMode.MAIN:
            return f"main:{job.effective_user}"
        return f"cron:isolated:{job.id}:{job.run_count}"


# ── Exceptions ──────────────────────────────────────────────────


class _RetriesExhaustedError(Exception):
    """All retry attempts exhausted."""

    def __init__(self, original_error: Exception | None = None) -> None:
        self.original_error = original_error
        super().__init__(str(original_error))


class CronBudgetExceededError(Exception):
    """Job skipped because LLM budget would be exceeded."""
