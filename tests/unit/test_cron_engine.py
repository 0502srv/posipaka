"""Tests for cron system: CronEngine, CronExecutor, CronHistory, CronParser.

Covers:
    - CronEngine: CRUD, persistence, retry fields, workflow registration,
      schedule validation, ID uniqueness, on_remove callbacks
    - CronExecutor: idempotency, concurrency limits, degradation gate,
      cost guard gate, DLQ on exhausted retries, metrics/hooks integration,
      job timeout, SSRF webhook validation, LRU lock cleanup
    - CronHistory: execution log, DLQ CRUD, stats with avg_duration, cleanup,
      WAL mode, uninitialized guard
    - CronParser: UA/RU/EN schedule parsing, all weekdays, intent detection
    - SessionManager: named persistent sessions
"""

from __future__ import annotations

import asyncio

import pytest

from posipaka.core.cron_engine import CronEngine, CronType

# Default schedule for tests that don't care about schedule
_CRON = {"cron": "0 9 * * *"}

# ═══════════════════════════════════════════════════════════════
# CronEngine
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def engine(tmp_path):
    e = CronEngine(tmp_path / "cron")
    e.init()
    return e


def test_add_and_list(engine):
    engine.add(name="test_job", message="Hello", user_id="u1",
               cron_type=CronType.RECURRING, cron="0 9 * * *")
    jobs = engine.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["name"] == "test_job"
    assert jobs[0]["schedule"] == "0 9 * * *"


def test_persistence(tmp_path):
    cron_dir = tmp_path / "cron"
    e1 = CronEngine(cron_dir)
    e1.init()
    e1.add(name="persistent", message="Hi", user_id="u1", **_CRON)

    e2 = CronEngine(cron_dir)
    e2.init()
    assert len(e2.list_jobs()) == 1
    assert e2.list_jobs()[0]["name"] == "persistent"


def test_remove_by_name(engine):
    engine.add(name="removable", message="Bye", user_id="u1", **_CRON)
    assert engine.remove("removable") is True
    assert len(engine.list_jobs()) == 0


def test_enable_disable(engine):
    job = engine.add(name="toggle", message="X", user_id="u1", **_CRON)
    engine.disable(job.id)
    assert engine.get(job.id).enabled is False
    engine.enable(job.id)
    assert engine.get(job.id).enabled is True


def test_mark_run_and_delete(engine):
    job = engine.add(name="once", message="One time", user_id="u1",
                     cron_type=CronType.ONE_SHOT, at="2026-04-01T09:00:00",
                     delete_after_run=True)
    engine.mark_run(job.id)
    assert len(engine.list_jobs()) == 0


def test_parse_every():
    assert CronEngine.parse_every("30m") == 1800
    assert CronEngine.parse_every("4h") == 14400
    assert CronEngine.parse_every("1d") == 86400


def test_delivery_mode_defaults(engine):
    job = engine.add(name="default", message="Hi", user_id="u1", **_CRON)
    assert job.effective_delivery == "announce"
    assert job.effective_channel == "telegram"
    assert job.effective_user == "u1"


def test_target_channel_override(engine):
    job = engine.add(name="cross", message="Hi", user_id="u1",
                     channel="telegram", target_channel="discord",
                     target_user_id="u2", **_CRON)
    assert job.effective_channel == "discord"
    assert job.effective_user == "u2"


def test_mark_error_and_retry(engine):
    job = engine.add(name="retry", message="X", user_id="u1",
                     max_retries=3, **_CRON)
    engine.mark_error(job.id, "timeout")
    assert job.consecutive_failures == 1
    assert engine.should_retry(job.id) is True

    for _ in range(3):
        engine.mark_error(job.id, "timeout")
    assert engine.should_retry(job.id) is False


def test_retry_delay_exponential_with_jitter(engine):
    job = engine.add(name="backoff", message="X", user_id="u1",
                     max_retries=3, retry_delay_seconds=10, **_CRON)
    engine.mark_error(job.id, "e1")
    delay1 = engine.get_retry_delay(job.id)
    assert 10 <= delay1 <= 12  # 10 + up to 20% jitter

    engine.mark_error(job.id, "e2")
    delay2 = engine.get_retry_delay(job.id)
    assert 20 <= delay2 <= 24  # 20 + up to 20% jitter

    engine.mark_error(job.id, "e3")
    delay3 = engine.get_retry_delay(job.id)
    assert 40 <= delay3 <= 48  # 40 + up to 20% jitter


def test_mark_run_resets_failures(engine):
    job = engine.add(name="reset", message="X", user_id="u1",
                     max_retries=3, **_CRON)
    engine.mark_error(job.id, "fail")
    engine.mark_run(job.id)
    assert job.consecutive_failures == 0
    assert job.last_error == ""


def test_workflow_registration(engine):
    job = engine.register_workflow("weekly_review", "0 18 * * 5", "u1")
    assert job.name == "workflow:weekly_review"
    assert job.type == "workflow"
    # Idempotent — returns same job
    job2 = engine.register_workflow("weekly_review", "0 18 * * 5", "u1")
    assert job2.id == job.id


def test_list_jobs_filter_by_user(engine):
    engine.add(name="j1", message="X", user_id="u1", **_CRON)
    engine.add(name="j2", message="Y", user_id="u2", **_CRON)
    assert len(engine.list_jobs(user_id="u1")) == 1
    assert len(engine.list_jobs()) == 2


def test_validation_invalid_cron_expression(engine):
    with pytest.raises(ValueError, match="expected 5 fields"):
        engine.add(name="bad_cron", message="X", user_id="u1",
                   cron_type=CronType.RECURRING, cron="invalid")


def test_validation_invalid_at_datetime(engine):
    with pytest.raises(ValueError, match="Invalid 'at'"):
        engine.add(name="bad_at", message="X", user_id="u1",
                   cron_type=CronType.ONE_SHOT, at="not-a-date")


def test_validation_invalid_every(engine):
    with pytest.raises(ValueError, match="Invalid 'every'"):
        engine.add(name="bad_every", message="X", user_id="u1",
                   cron_type=CronType.INTERVAL, every="abc")


def test_validation_valid_formats(engine):
    engine.add(name="ok_cron", message="X", user_id="u1",
               cron_type=CronType.RECURRING, cron="0 9 * * *")
    engine.add(name="ok_at", message="X", user_id="u1",
               cron_type=CronType.ONE_SHOT, at="2026-04-01T09:00:00")
    engine.add(name="ok_every", message="X", user_id="u1",
               cron_type=CronType.INTERVAL, every="30m")
    assert len(engine.list_jobs()) == 3


def test_validation_mutual_exclusivity(engine):
    with pytest.raises(ValueError, match="Only one"):
        engine.add(name="bad", message="X", user_id="u1",
                   cron_type=CronType.RECURRING,
                   cron="0 9 * * *", every="30m")


def test_validation_negative_interval(engine):
    with pytest.raises(ValueError, match="Invalid 'every'"):
        engine.add(name="neg", message="X", user_id="u1",
                   cron_type=CronType.INTERVAL, every="-5m")


def test_validation_no_schedule_raises(engine):
    """Creating a non-workflow job without schedule must fail."""
    with pytest.raises(ValueError, match="Schedule required"):
        engine.add(name="ghost", message="X", user_id="u1",
                   cron_type=CronType.RECURRING)


def test_parse_every_seconds():
    assert CronEngine.parse_every("60s") == 60
    assert CronEngine.parse_every("1h") == 3600


def test_retry_delay_capped(engine):
    """Backoff capped at 1 hour."""
    job = engine.add(name="cap", message="X", user_id="u1",
                     max_retries=20, retry_delay_seconds=60, **_CRON)
    for _ in range(15):
        engine.mark_error(job.id, "e")
    delay = engine.get_retry_delay(job.id)
    assert delay <= 3600 * 1.2  # 3600 + 20% jitter max


def test_new_fields_persist(tmp_path):
    cron_dir = tmp_path / "cron"
    e1 = CronEngine(cron_dir)
    e1.init()
    e1.add(name="full", message="Test", user_id="u1",
           cron_type=CronType.RECURRING, cron="0 9 * * *",
           delivery_mode="webhook", webhook_url="https://example.com",
           max_retries=5, session_mode="custom", session_name="my_session",
           workflow_name="daily_brief", target_channel="discord",
           target_user_id="u99", timeout_seconds=120,
           misfire_policy="skip")

    e2 = CronEngine(cron_dir)
    e2.init()
    restored = e2.get("full")
    assert restored.webhook_url == "https://example.com"
    assert restored.max_retries == 5
    assert restored.session_name == "my_session"
    assert restored.target_channel == "discord"
    assert restored.timeout_seconds == 120
    assert restored.misfire_policy == "skip"


def test_on_remove_callback(engine):
    """on_remove callbacks fire when job is removed by ID or name."""
    removed_ids = []
    engine.on_remove(lambda jid: removed_ids.append(jid))

    j1 = engine.add(name="a", message="X", user_id="u1", **_CRON)
    j2 = engine.add(name="b", message="Y", user_id="u1", **_CRON)

    engine.remove(j1.id)      # remove by ID
    engine.remove("b")        # remove by name

    assert j1.id in removed_ids
    assert j2.id in removed_ids


def test_update_next_run(engine):
    job = engine.add(name="nr", message="X", user_id="u1", **_CRON)
    engine.update_next_run(job.id, "2026-04-01T09:00:00")
    assert engine.get(job.id).next_run_at == "2026-04-01T09:00:00"


def test_unique_ids_no_collision(engine):
    """All generated IDs must be unique."""
    ids = set()
    for i in range(50):
        job = engine.add(name=f"job_{i}", message="X", user_id="u1", **_CRON)
        ids.add(job.id)
    assert len(ids) == 50


def test_update_job_fields(engine):
    job = engine.add(name="upd", message="X", user_id="u1", **_CRON)
    updated = engine.update(job.id, message="New message", timezone="UTC")
    assert updated.message == "New message"
    assert updated.timezone == "UTC"


def test_update_nonexistent_raises(engine):
    with pytest.raises(ValueError, match="not found"):
        engine.update("nonexistent", message="X")


def test_update_readonly_field_rejected(engine):
    job = engine.add(name="ro", message="X", user_id="u1", **_CRON)
    with pytest.raises(ValueError, match="readonly"):
        engine.update(job.id, run_count=99)


def test_update_unknown_field_rejected(engine):
    job = engine.add(name="unk", message="X", user_id="u1", **_CRON)
    with pytest.raises(ValueError, match="Unknown"):
        engine.update(job.id, nonexistent_field="value")


def test_update_revalidates_schedule(engine):
    job = engine.add(name="revalidate", message="X", user_id="u1", **_CRON)
    with pytest.raises(ValueError, match="expected 5 fields"):
        engine.update(job.id, cron="bad")


def test_updated_at_set_on_save(engine):
    job = engine.add(name="ts", message="X", user_id="u1", **_CRON)
    assert job.updated_at != ""


def test_atomic_save_no_tmp_files(tmp_path):
    """After save, no .tmp files should remain."""
    cron_dir = tmp_path / "cron"
    e = CronEngine(cron_dir)
    e.init()
    e.add(name="atomic", message="X", user_id="u1", **_CRON)
    tmp_files = list(cron_dir.glob("*.tmp"))
    assert len(tmp_files) == 0


# ═══════════════════════════════════════════════════════════════
# CronHistory + DLQ
# ═══════════════════════════════════════════════════════════════


class TestCronHistory:
    @pytest.fixture
    def history(self, tmp_path):
        from posipaka.core.cron_history import CronHistory
        h = CronHistory(tmp_path / "cron_history.db")
        h.init()
        return h

    def test_record_success_with_duration(self, history):
        eid = history.record_start("j1", "test_job")
        history.record_success(eid, "OK", duration_sec=1.23)
        runs = history.get_runs("j1")
        assert runs[0]["status"] == "success"
        assert runs[0]["duration_sec"] == 1.23

    def test_record_failure(self, history):
        eid = history.record_start("j1", "test_job")
        history.record_failure(eid, "timeout error")
        runs = history.get_runs("j1")
        assert runs[0]["status"] == "failed"

    def test_get_stats_with_avg_duration(self, history):
        for i in range(4):
            eid = history.record_start("j1", "job")
            if i < 3:
                history.record_success(eid, "ok", duration_sec=float(i + 1))
            else:
                history.record_failure(eid, "err")
        stats = history.get_stats("j1")
        assert stats["total"] == 4
        assert stats["success"] == 3
        assert stats["failed"] == 1
        assert stats["avg_duration"] == 2.0  # (1+2+3)/3

    def test_uninitialized_guard(self, tmp_path):
        """Methods must raise RuntimeError if init() not called."""
        from posipaka.core.cron_history import CronHistory
        h = CronHistory(tmp_path / "not_init.db")
        with pytest.raises(RuntimeError, match="not initialized"):
            h.record_start("j1", "job")

    # ── DLQ ──

    def test_dlq_add_and_list(self, history):
        dlq_id = history.add_to_dlq("j1", "failing_job", "fatal error", attempts=3)
        assert dlq_id > 0
        entries = history.get_dlq()
        assert len(entries) == 1
        assert entries[0]["job_name"] == "failing_job"
        assert entries[0]["attempts"] == 3
        assert entries[0]["status"] == "pending"

    def test_dlq_resolve(self, history):
        dlq_id = history.add_to_dlq("j1", "job", "error", attempts=1)
        assert history.resolve_dlq(dlq_id, "manual_retry") is True
        # Should not appear in pending list
        assert len(history.get_dlq("pending")) == 0
        assert len(history.get_dlq("resolved")) == 1

    def test_dlq_count(self, history):
        assert history.dlq_count() == 0
        history.add_to_dlq("j1", "a", "e", 1)
        history.add_to_dlq("j2", "b", "e", 1)
        assert history.dlq_count() == 2

    def test_dlq_format(self, history):
        history.add_to_dlq("j1", "my_job", "some error", 5)
        text = history.format_dlq()
        assert "my_job" in text
        assert "5 attempts" in text

    def test_dlq_empty_format(self, history):
        assert "порожній" in history.format_dlq()

    def test_cleanup_includes_resolved_dlq(self, history):
        eid = history.record_start("j1", "job")
        history.record_success(eid, "ok")
        dlq_id = history.add_to_dlq("j1", "job", "err", 1)
        history.resolve_dlq(dlq_id)
        count = history.cleanup(days=0)
        assert count >= 1
        assert history.dlq_count() == 0

    def test_format_runs_with_duration(self, history):
        eid = history.record_start("j1", "my_job")
        history.record_success(eid, "done", duration_sec=2.5)
        text = history.format_runs()
        assert "2.5s" in text


# ═══════════════════════════════════════════════════════════════
# CronExecutor
# ═══════════════════════════════════════════════════════════════


class TestCronExecutor:
    @pytest.fixture
    def setup(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()

        from posipaka.core.cron_history import CronHistory
        history = CronHistory(tmp_path / "history.db")
        history.init()

        from posipaka.core.cron_executor import CronExecutor
        executor = CronExecutor(engine, history=history)
        return engine, executor, history

    @staticmethod
    def _mock_agent(**kwargs):
        async def fn(**kw):
            return f"Result: {kw['message']}"
        return fn

    # ── Basic execution ──

    @pytest.mark.asyncio
    async def test_execute_simple(self, setup):
        engine, executor, history = setup
        job = engine.add(name="simple", message="Hello", user_id="u1", **_CRON)

        result = await executor.execute_job(job, agent_fn=self._mock_agent())
        assert result == "Result: Hello"
        assert engine.get(job.id).run_count == 1

        runs = history.get_runs(job.id)
        assert len(runs) == 1
        assert runs[0]["status"] == "success"
        assert runs[0]["duration_sec"] is not None

    @pytest.mark.asyncio
    async def test_disabled_job_skipped(self, setup):
        engine, executor, _ = setup
        job = engine.add(name="off", message="X", user_id="u1", **_CRON)
        engine.disable(job.id)
        result = await executor.execute_job(job, agent_fn=self._mock_agent())
        assert result is None

    # ── Idempotency ──

    @pytest.mark.asyncio
    async def test_idempotency_blocks_concurrent(self, setup):
        """Same job cannot run twice concurrently."""
        engine, executor, _ = setup
        job = engine.add(name="slow", message="X", user_id="u1", **_CRON)

        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_fn(**kw):
            started.set()
            await release.wait()
            return "done"

        task = asyncio.create_task(executor.execute_job(job, agent_fn=slow_fn))
        await started.wait()

        # Second call — should be rejected
        dup = await executor.execute_job(job, agent_fn=slow_fn)
        assert dup is None

        release.set()
        result = await task
        assert result == "done"

    # ── Backpressure ──

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, tmp_path):
        """Semaphore limits concurrent execution."""
        from posipaka.core.cron_executor import CronExecutor
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        executor = CronExecutor(engine, max_concurrent=2)

        running = 0
        max_running = 0
        lock = asyncio.Lock()
        barrier = asyncio.Event()

        async def counting_fn(**kw):
            nonlocal running, max_running
            async with lock:
                running += 1
                max_running = max(max_running, running)
            await barrier.wait()
            async with lock:
                running -= 1
            return "ok"

        jobs = [engine.add(name=f"j{i}", message="X", user_id="u1", **_CRON)
                for i in range(4)]
        tasks = [asyncio.create_task(executor.execute_job(j, agent_fn=counting_fn))
                 for j in jobs]

        await asyncio.sleep(0.05)
        barrier.set()
        await asyncio.gather(*tasks)

        assert max_running <= 2

    # ── Retry + DLQ ──

    @pytest.mark.asyncio
    async def test_retry_then_dlq(self, setup):
        """After exhausting retries, job lands in DLQ."""
        engine, executor, history = setup
        job = engine.add(name="fragile", message="X", user_id="u1",
                         max_retries=2, retry_delay_seconds=0, **_CRON)

        async def always_fail(**kw):
            raise RuntimeError("permanent failure")

        result = await executor.execute_job(job, agent_fn=always_fail)
        assert result is None

        # Should be in DLQ
        dlq = history.get_dlq()
        assert len(dlq) == 1
        assert dlq[0]["job_name"] == "fragile"
        assert dlq[0]["attempts"] == 3  # 1 + 2 retries

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_third(self, setup):
        engine, executor, _ = setup
        job = engine.add(name="flaky", message="X", user_id="u1",
                         max_retries=2, retry_delay_seconds=0, **_CRON)

        attempts = 0
        async def flaky_fn(**kw):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("transient")
            return "recovered"

        result = await executor.execute_job(job, agent_fn=flaky_fn)
        assert result == "recovered"
        assert attempts == 3

    # ── Timeout ──

    @pytest.mark.asyncio
    async def test_job_timeout(self, setup):
        """Job that exceeds timeout_seconds must fail."""
        engine, executor, history = setup
        job = engine.add(name="hung", message="X", user_id="u1",
                         timeout_seconds=1, **_CRON)

        async def hang_fn(**kw):
            await asyncio.sleep(10)
            return "never"

        result = await executor.execute_job(job, agent_fn=hang_fn)
        assert result is None

        runs = history.get_runs(job.id)
        assert runs[0]["status"] == "failed"

    # ── Degradation gate ──

    @pytest.mark.asyncio
    async def test_emergency_mode_blocks(self, tmp_path):
        """Jobs skipped in EMERGENCY mode."""
        from unittest.mock import MagicMock

        from posipaka.core.cron_executor import CronExecutor

        engine = CronEngine(tmp_path / "cron")
        engine.init()

        mock_degradation = MagicMock()
        mock_degradation.mode = "emergency"

        executor = CronExecutor(engine, degradation=mock_degradation)
        job = engine.add(name="blocked", message="X", user_id="u1", **_CRON)

        result = await executor.execute_job(job, agent_fn=self._mock_agent())
        assert result is None

    @pytest.mark.asyncio
    async def test_full_mode_allows(self, tmp_path):
        from unittest.mock import MagicMock

        from posipaka.core.cron_executor import CronExecutor

        engine = CronEngine(tmp_path / "cron")
        engine.init()

        mock_degradation = MagicMock()
        mock_degradation.mode = "full"

        executor = CronExecutor(engine, degradation=mock_degradation)
        job = engine.add(name="allowed", message="X", user_id="u1", **_CRON)

        result = await executor.execute_job(job, agent_fn=self._mock_agent())
        assert result == "Result: X"

    # ── Cost guard gate ──

    @pytest.mark.asyncio
    async def test_cost_guard_blocks(self, tmp_path):
        """Job fails if budget exceeded."""
        from unittest.mock import MagicMock

        from posipaka.core.cron_executor import CronExecutor

        engine = CronEngine(tmp_path / "cron")
        engine.init()

        mock_cost = MagicMock()
        mock_cost.check_before_call.return_value = (False, "daily budget exceeded")
        mock_cost.estimate_tokens.return_value = 100

        from posipaka.core.cron_history import CronHistory
        history = CronHistory(tmp_path / "hist.db")
        history.init()

        executor = CronExecutor(engine, cost_guard=mock_cost, history=history)
        job = engine.add(name="expensive", message="X", user_id="u1", **_CRON)

        result = await executor.execute_job(job, agent_fn=self._mock_agent())
        # Should fail and go to history as error
        assert result is None
        runs = history.get_runs(job.id)
        assert runs[0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_cost_guard_allows(self, tmp_path):
        from unittest.mock import MagicMock

        from posipaka.core.cron_executor import CronExecutor

        engine = CronEngine(tmp_path / "cron")
        engine.init()

        mock_cost = MagicMock()
        mock_cost.check_before_call.return_value = (True, "ok")
        mock_cost.estimate_tokens.return_value = 100

        executor = CronExecutor(engine, cost_guard=mock_cost)
        job = engine.add(name="cheap", message="X", user_id="u1", **_CRON)

        result = await executor.execute_job(job, agent_fn=self._mock_agent())
        assert result == "Result: X"

    # ── Hooks ──

    @pytest.mark.asyncio
    async def test_hooks_emitted(self, tmp_path):
        """JOB_TRIGGERED and JOB_COMPLETED hooks fire."""
        from posipaka.core.cron_executor import CronExecutor
        from posipaka.core.hooks.manager import HookEvent, HookManager

        engine = CronEngine(tmp_path / "cron")
        engine.init()

        hooks = HookManager()
        events_fired = []

        @hooks.on(HookEvent.JOB_TRIGGERED)
        def on_trigger(data):
            events_fired.append(("triggered", data["job_name"]))

        @hooks.on(HookEvent.JOB_COMPLETED)
        def on_complete(data):
            events_fired.append(("completed", data["job_name"]))

        executor = CronExecutor(engine, hooks=hooks)
        job = engine.add(name="observable", message="X", user_id="u1", **_CRON)

        await executor.execute_job(job, agent_fn=self._mock_agent())

        assert ("triggered", "observable") in events_fired
        assert ("completed", "observable") in events_fired

    @pytest.mark.asyncio
    async def test_failed_hook_emitted(self, tmp_path):
        from posipaka.core.cron_executor import CronExecutor
        from posipaka.core.cron_history import CronHistory
        from posipaka.core.hooks.manager import HookEvent, HookManager

        engine = CronEngine(tmp_path / "cron")
        engine.init()
        history = CronHistory(tmp_path / "h.db")
        history.init()

        hooks = HookManager()
        failures = []

        @hooks.on(HookEvent.JOB_FAILED)
        def on_fail(data):
            failures.append(data["job_name"])

        executor = CronExecutor(engine, hooks=hooks, history=history)
        job = engine.add(name="doomed", message="X", user_id="u1", **_CRON)

        async def fail_fn(**kw):
            raise RuntimeError("boom")

        await executor.execute_job(job, agent_fn=fail_fn)
        assert "doomed" in failures

    # ── SLO metrics ──

    @pytest.mark.asyncio
    async def test_slo_metrics_recorded(self, tmp_path):
        from unittest.mock import MagicMock

        from posipaka.core.cron_executor import CronExecutor

        engine = CronEngine(tmp_path / "cron")
        engine.init()

        mock_slo = MagicMock()
        executor = CronExecutor(engine, slo_monitor=mock_slo)
        job = engine.add(name="metered", message="X", user_id="u1", **_CRON)

        await executor.execute_job(job, agent_fn=self._mock_agent())

        mock_slo.record.assert_called()
        call_args = mock_slo.record.call_args
        assert call_args[0][0] == "cron_job_duration"

    # ── Session resolution ──

    @pytest.mark.asyncio
    async def test_session_isolated_unique_per_run(self, setup):
        """Isolated sessions get unique ID per run."""
        engine, executor, _ = setup
        job = engine.add(name="iso", message="X", user_id="u1",
                         session_mode="isolated", **_CRON)

        sessions_seen = []
        async def capture_fn(**kw):
            sessions_seen.append(kw.get("session_id"))
            return "ok"

        await executor.execute_job(job, agent_fn=capture_fn)
        await executor.execute_job(job, agent_fn=capture_fn)
        assert len(sessions_seen) == 2
        assert sessions_seen[0] != sessions_seen[1]

    @pytest.mark.asyncio
    async def test_session_custom_stable(self, setup):
        """Custom sessions keep same ID across runs."""
        engine, executor, _ = setup
        job = engine.add(name="custom", message="X", user_id="u1",
                         session_mode="custom", session_name="standup", **_CRON)

        sessions_seen = []
        async def capture_fn(**kw):
            sessions_seen.append(kw.get("session_id"))
            return "ok"

        await executor.execute_job(job, agent_fn=capture_fn)
        await executor.execute_job(job, agent_fn=capture_fn)
        assert sessions_seen[0] == sessions_seen[1]
        assert "standup" in sessions_seen[0]

    # ── Concurrency available ──

    @pytest.mark.asyncio
    async def test_concurrency_available(self, setup):
        engine, executor, _ = setup
        assert executor.concurrency_available == 5  # default max_concurrent

        job = engine.add(name="c", message="X", user_id="u1", **_CRON)
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_fn(**kw):
            started.set()
            await release.wait()
            return "ok"

        task = asyncio.create_task(executor.execute_job(job, agent_fn=slow_fn))
        await started.wait()
        assert executor.concurrency_available == 4

        release.set()
        await task
        assert executor.concurrency_available == 5

    # ── Graceful shutdown ──

    @pytest.mark.asyncio
    async def test_graceful_shutdown_empty(self, setup):
        _, executor, _ = setup
        await executor.graceful_shutdown(timeout=1.0)

    @pytest.mark.asyncio
    async def test_running_jobs_tracking(self, setup):
        engine, executor, _ = setup
        job = engine.add(name="track", message="X", user_id="u1", **_CRON)

        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_fn(**kw):
            started.set()
            await release.wait()
            return "ok"

        task = asyncio.create_task(executor.execute_job(job, agent_fn=slow_fn))
        await started.wait()

        assert job.id in executor.running_jobs
        release.set()
        await task
        assert job.id not in executor.running_jobs


# ═══════════════════════════════════════════════════════════════
# CronParser
# ═══════════════════════════════════════════════════════════════


class TestCronParser:
    def test_detect_intent_ua(self):
        from posipaka.core.cron_parser import detect_schedule_intent
        assert detect_schedule_intent("нагадай мені через 30 хвилин") is True
        assert detect_schedule_intent("щодня о 9 ранку") is True
        assert detect_schedule_intent("як справи?") is False

    def test_detect_intent_en(self):
        from posipaka.core.cron_parser import detect_schedule_intent
        assert detect_schedule_intent("remind me in 30 minutes") is True
        assert detect_schedule_intent("every day at 9") is True
        assert detect_schedule_intent("what is the weather?") is False

    def test_parse_relative_ua(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("нагадай через 30 хвилин")
        assert result.is_valid
        assert result.cron_type == CronType.ONE_SHOT
        assert result.at

    def test_parse_daily_ua(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("щодня о 9:30")
        assert result.is_valid
        assert result.cron == "30 9 * * *"

    def test_parse_daily_en(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("every day at 14")
        assert result.is_valid
        assert result.cron == "0 14 * * *"

    def test_parse_interval(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("кожні 15 хвилин")
        assert result.is_valid
        assert result.cron_type == CronType.INTERVAL
        assert result.every == "15m"

    def test_parse_unknown(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("яка погода?")
        assert not result.is_valid

    # ── All weekdays ──

    def test_parse_weekday_saturday_ua(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("щосуботи о 10:00")
        assert result.is_valid
        assert result.cron_type == CronType.RECURRING
        assert result.cron == "0 10 * * sat"

    def test_parse_weekday_sunday_ua(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("щонеділі о 12")
        assert result.is_valid
        assert result.cron == "0 12 * * sun"

    def test_parse_weekday_monday_en(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("every monday at 9:30")
        assert result.is_valid
        assert result.cron == "30 9 * * mon"

    def test_parse_weekday_friday_en(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("friday at 18")
        assert result.is_valid
        assert result.cron == "0 18 * * fri"

    def test_parse_weekday_saturday_en(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("every saturday at 8")
        assert result.is_valid
        assert result.cron == "0 8 * * sat"

    def test_parse_weekday_sunday_en(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("sunday at 20:30")
        assert result.is_valid
        assert result.cron == "30 20 * * sun"

    # ── Monthly ──

    def test_parse_monthly_ua(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("кожного 1-го о 9")
        assert result.is_valid
        assert result.cron == "0 9 1 * *"

    def test_parse_monthly_ua_with_minutes(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("щомісяця 15 о 10:30")
        assert result.is_valid
        assert result.cron == "30 10 15 * *"

    def test_parse_monthly_en(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("every 15th at 10:30")
        assert result.is_valid
        assert result.cron == "30 10 15 * *"

    def test_parse_monthly_en_simple(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("monthly on 1 at 9")
        assert result.is_valid
        assert result.cron == "0 9 1 * *"

    def test_parse_monthly_ru(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("каждого 5-го в 8")
        assert result.is_valid
        assert result.cron == "0 8 5 * *"

    def test_detect_intent_monthly(self):
        from posipaka.core.cron_parser import detect_schedule_intent
        assert detect_schedule_intent("щомісяця 1 о 9") is True
        assert detect_schedule_intent("monthly on 15 at 10") is True
        assert detect_schedule_intent("кожного 1-го о 9") is True


# ═══════════════════════════════════════════════════════════════
# CronExecutor — webhook tracking
# ═══════════════════════════════════════════════════════════════


class TestCronExecutorWebhook:
    def test_webhook_tasks_set_exists(self, tmp_path):
        from posipaka.core.cron_executor import CronExecutor
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        executor = CronExecutor(engine)
        assert hasattr(executor, "_webhook_tasks")
        assert isinstance(executor._webhook_tasks, set)


# ═══════════════════════════════════════════════════════════════
# SessionManager (named sessions)
# ═══════════════════════════════════════════════════════════════


class TestSessionManager:
    def test_named_session_stable(self):
        from posipaka.core.session import SessionManager
        mgr = SessionManager()
        s1 = mgr.get_or_create_named("daily", "u1", "telegram")
        s2 = mgr.get_or_create_named("daily", "u1", "telegram")
        assert s1.id == s2.id

    def test_close_named_removes(self):
        from posipaka.core.session import SessionManager
        mgr = SessionManager()
        s = mgr.get_or_create_named("test", "u1", "telegram")
        mgr.close(s.id)
        assert mgr.get_named("test") is None


# ═══════════════════════════════════════════════════════════════
# Edge cases & additional coverage
# ═══════════════════════════════════════════════════════════════


class TestCronParserEdgeCases:
    """Parser validation and false-positive prevention."""

    def test_invalid_hour_rejected(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("щодня о 25:00")
        assert not result.is_valid

    def test_invalid_minute_rejected(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("every day at 9:70")
        assert not result.is_valid

    def test_invalid_monthly_day_rejected(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("monthly on 35 at 9")
        assert not result.is_valid

    def test_invalid_monthly_hour_rejected(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("кожного 1-го о 30")
        assert not result.is_valid

    def test_no_false_positive_in_number(self):
        """'in 1990' should not trigger schedule intent."""
        from posipaka.core.cron_parser import detect_schedule_intent
        assert detect_schedule_intent("I was born in 1990") is False
        assert detect_schedule_intent("there are 5 items in 3 boxes") is False

    def test_intent_still_detects_valid_en(self):
        from posipaka.core.cron_parser import detect_schedule_intent
        assert detect_schedule_intent("in 5 minutes do something") is True
        assert detect_schedule_intent("in 2 hours check status") is True

    def test_zero_interval_rejected(self):
        from posipaka.core.cron_parser import parse_schedule
        # "кожні 0 хвилин" should not produce valid schedule
        result = parse_schedule("кожні 0 хвилин")
        assert not result.is_valid

    def test_weekday_invalid_hour(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("every monday at 25")
        assert not result.is_valid


class TestCronHistoryContextManager:
    def test_context_manager(self, tmp_path):
        from posipaka.core.cron_history import CronHistory
        with CronHistory(tmp_path / "ctx.db") as h:
            eid = h.record_start("j1", "job")
            h.record_success(eid, "ok")
            assert h.get_runs("j1")[0]["status"] == "success"
        # After exit, connection is closed
        assert h._conn is None


class TestCronExecutorAllEnabled:
    @pytest.fixture
    def setup(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        from posipaka.core.cron_executor import CronExecutor
        executor = CronExecutor(engine)
        return engine, executor

    @pytest.mark.asyncio
    async def test_execute_all_enabled_runs_enabled_only(self, setup):
        engine, executor = setup
        j1 = engine.add(name="on", message="A", user_id="u1", **_CRON)
        j2 = engine.add(name="off", message="B", user_id="u1", **_CRON)
        engine.disable(j2.id)

        async def fn(**kw):
            return f"done:{kw['message']}"

        ids = await executor.execute_all_enabled(agent_fn=fn)
        assert j1.id in ids
        assert j2.id not in ids

    @pytest.mark.asyncio
    async def test_execute_all_enabled_handles_failure(self, setup):
        engine, executor = setup
        j1 = engine.add(name="ok", message="A", user_id="u1", **_CRON)
        j2 = engine.add(name="bad", message="B", user_id="u1", **_CRON)

        call_count = 0

        async def flaky_fn(**kw):
            nonlocal call_count
            call_count += 1
            if kw["message"] == "B":
                raise RuntimeError("fail")
            return "ok"

        ids = await executor.execute_all_enabled(agent_fn=flaky_fn)
        assert j1.id in ids
        assert j2.id not in ids


class TestCronExecutorShutdown:
    @pytest.mark.asyncio
    async def test_graceful_shutdown_waits_for_running(self, tmp_path):
        """Shutdown waits for running jobs to complete."""
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        from posipaka.core.cron_executor import CronExecutor
        executor = CronExecutor(engine)

        job = engine.add(name="slow", message="X", user_id="u1", **_CRON)
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_fn(**kw):
            started.set()
            await release.wait()
            return "ok"

        task = asyncio.create_task(executor.execute_job(job, agent_fn=slow_fn))
        await started.wait()

        assert len(executor.running_jobs) == 1

        # Start shutdown with short timeout — release before it expires
        async def release_soon():
            await asyncio.sleep(0.1)
            release.set()

        asyncio.create_task(release_soon())
        await executor.graceful_shutdown(timeout=5.0)
        await task

        assert len(executor.running_jobs) == 0

    @pytest.mark.asyncio
    async def test_graceful_shutdown_timeout_orphans(self, tmp_path):
        """Shutdown reports orphaned jobs if they don't finish in time."""
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        from posipaka.core.cron_executor import CronExecutor
        executor = CronExecutor(engine)

        job = engine.add(name="stuck", message="X", user_id="u1", **_CRON)
        started = asyncio.Event()

        async def hang_fn(**kw):
            started.set()
            await asyncio.sleep(60)
            return "never"

        task = asyncio.create_task(executor.execute_job(job, agent_fn=hang_fn))
        await started.wait()

        # Very short timeout — will leave job orphaned
        await executor.graceful_shutdown(timeout=0.2)
        assert len(executor.running_jobs) == 1

        # Cleanup
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestCronJobFromDictUnknownFields:
    def test_unknown_fields_ignored(self):
        """from_dict silently drops unknown fields."""
        data = {
            "id": "abc",
            "name": "test",
            "type": "recurring",
            "message": "Hello",
            "user_id": "u1",
            "unknown_field": "value",
            "another_bad": 42,
        }
        from posipaka.core.cron_engine import CronJob
        job = CronJob.from_dict(data)
        assert job.name == "test"
        assert not hasattr(job, "unknown_field")


class TestCronEngineUpdateScheduleRevalidation:
    def test_update_schedule_type_change_validates(self, tmp_path):
        """Changing type + schedule in update triggers re-validation."""
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        job = engine.add(name="v", message="X", user_id="u1", **_CRON)

        # Valid change: recurring → interval
        updated = engine.update(job.id, type="interval", every="30m", cron="")
        assert updated.type == "interval"
        assert updated.every == "30m"

    def test_update_to_invalid_interval_rejected(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        job = engine.add(name="v2", message="X", user_id="u1", **_CRON)

        with pytest.raises(ValueError):
            engine.update(job.id, type="interval", every="bad", cron="")


class TestDeepCronValidation:
    """APScheduler-level cron expression validation."""

    def test_invalid_cron_values_rejected(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        with pytest.raises(ValueError, match="Invalid cron"):
            engine.add(name="bad", message="X", user_id="u1",
                       cron_type=CronType.RECURRING, cron="99 99 * * *")

    def test_invalid_day_of_week_rejected(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        with pytest.raises(ValueError, match="Invalid cron"):
            engine.add(name="bad_dow", message="X", user_id="u1",
                       cron_type=CronType.RECURRING, cron="0 9 * * 8")

    def test_valid_cron_accepted(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        job = engine.add(name="valid", message="X", user_id="u1",
                         cron_type=CronType.RECURRING, cron="30 14 1 */2 mon")
        assert job.cron == "30 14 1 */2 mon"


class TestCircuitBreaker:
    """Auto-disable after consecutive failures."""

    def test_auto_disable_after_threshold(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        job = engine.add(name="fragile", message="X", user_id="u1",
                         auto_disable_after=3, **_CRON)
        for _ in range(3):
            engine.mark_error(job.id, "boom")
        assert job.enabled is False
        assert job.consecutive_failures == 3

    def test_no_auto_disable_below_threshold(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        job = engine.add(name="ok", message="X", user_id="u1",
                         auto_disable_after=5, **_CRON)
        for _ in range(4):
            engine.mark_error(job.id, "err")
        assert job.enabled is True

    def test_auto_disable_zero_means_never(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        job = engine.add(name="never", message="X", user_id="u1",
                         auto_disable_after=0, **_CRON)
        for _ in range(50):
            engine.mark_error(job.id, "err")
        assert job.enabled is True

    def test_reset_after_success(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        job = engine.add(name="recover", message="X", user_id="u1",
                         auto_disable_after=3, **_CRON)
        engine.mark_error(job.id, "e1")
        engine.mark_error(job.id, "e2")
        engine.mark_run(job.id)
        engine.mark_error(job.id, "e3")
        engine.mark_error(job.id, "e4")
        assert job.enabled is True  # reset at mark_run


class TestUniqueJobNames:
    """Name uniqueness + O(1) lookup."""

    def test_duplicate_name_rejected(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        engine.add(name="unique", message="X", user_id="u1", **_CRON)
        with pytest.raises(ValueError, match="already exists"):
            engine.add(name="unique", message="Y", user_id="u1", **_CRON)

    def test_name_freed_after_remove(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        engine.add(name="reuse", message="X", user_id="u1", **_CRON)
        engine.remove("reuse")
        # Name should be free now
        job = engine.add(name="reuse", message="Y", user_id="u1", **_CRON)
        assert job.message == "Y"

    def test_name_index_survives_reload(self, tmp_path):
        cron_dir = tmp_path / "cron"
        e1 = CronEngine(cron_dir)
        e1.init()
        e1.add(name="indexed", message="X", user_id="u1", **_CRON)

        e2 = CronEngine(cron_dir)
        e2.init()
        # Should find by name in O(1)
        assert e2.get("indexed") is not None
        # Should reject duplicate
        with pytest.raises(ValueError, match="already exists"):
            e2.add(name="indexed", message="Y", user_id="u1", **_CRON)

    def test_update_rename_checks_uniqueness(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        j1 = engine.add(name="a", message="X", user_id="u1", **_CRON)
        engine.add(name="b", message="Y", user_id="u1", **_CRON)
        with pytest.raises(ValueError, match="already exists"):
            engine.update(j1.id, name="b")

    def test_update_rename_succeeds(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        j = engine.add(name="old", message="X", user_id="u1", **_CRON)
        engine.update(j.id, name="new")
        assert engine.get("new") is not None
        assert engine.get("old") is None


class TestCronParserTimezone:
    """Timezone-aware relative time parsing."""

    def test_parse_with_timezone(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("через 30 хвилин", tz="Europe/Kyiv")
        assert result.is_valid
        assert result.cron_type == CronType.ONE_SHOT
        assert result.at  # ISO datetime in UTC

    def test_parse_with_invalid_timezone_falls_back(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("in 10 minutes", tz="Invalid/Zone")
        assert result.is_valid  # should still work with UTC fallback

    def test_parse_input_truncated(self):
        """Long input is truncated, no ReDoS."""
        from posipaka.core.cron_parser import parse_schedule
        long_text = "X" * 1000 + " through 30 minutes"
        result = parse_schedule(long_text)
        assert not result.is_valid  # schedule part truncated away


class TestCronHistoryCleanupCount:
    """cleanup() returns total count."""

    def test_cleanup_counts_both_tables(self, tmp_path):
        from posipaka.core.cron_history import CronHistory
        h = CronHistory(tmp_path / "cleanup.db")
        h.init()

        eid = h.record_start("j1", "job")
        h.record_success(eid, "ok")
        dlq_id = h.add_to_dlq("j2", "job2", "err", 1)
        h.resolve_dlq(dlq_id)

        count = h.cleanup(days=0)
        assert count >= 2  # at least 1 exec + 1 resolved DLQ


class TestCronHistoryAsyncContextManager:
    """Async context manager."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self, tmp_path):
        from posipaka.core.cron_history import CronHistory
        h = CronHistory(tmp_path / "async_ctx.db")
        async with h:
            eid = h.record_start("j1", "job")
            h.record_success(eid, "ok")
        assert h._conn is None


class TestCronExecutorClose:
    """Explicit close() for resource cleanup."""

    @pytest.mark.asyncio
    async def test_close_clears_webhook_tasks(self, tmp_path):
        from posipaka.core.cron_executor import CronExecutor
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        executor = CronExecutor(engine)
        await executor.close()
        assert len(executor._webhook_tasks) == 0

    @pytest.mark.asyncio
    async def test_close_idempotent(self, tmp_path):
        from posipaka.core.cron_executor import CronExecutor
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        executor = CronExecutor(engine)
        await executor.close()
        await executor.close()  # no error


class TestAutoDisableField:
    """auto_disable_after persists and loads correctly."""

    def test_auto_disable_after_persists(self, tmp_path):
        cron_dir = tmp_path / "cron"
        e1 = CronEngine(cron_dir)
        e1.init()
        e1.add(name="persist", message="X", user_id="u1",
               auto_disable_after=5, **_CRON)

        e2 = CronEngine(cron_dir)
        e2.init()
        job = e2.get("persist")
        assert job.auto_disable_after == 5


class TestMaxJobsLimit:
    """CronEngine enforces max_jobs limit."""

    def test_max_jobs_exceeded(self, tmp_path):
        engine = CronEngine(tmp_path / "cron", max_jobs=3)
        engine.init()
        for i in range(3):
            engine.add(name=f"j{i}", message="X", user_id="u1", **_CRON)
        with pytest.raises(ValueError, match="Maximum number"):
            engine.add(name="overflow", message="X", user_id="u1", **_CRON)

    def test_max_jobs_allows_after_remove(self, tmp_path):
        engine = CronEngine(tmp_path / "cron", max_jobs=2)
        engine.init()
        engine.add(name="a", message="X", user_id="u1", **_CRON)
        engine.add(name="b", message="X", user_id="u1", **_CRON)
        engine.remove("a")
        # Should work now
        engine.add(name="c", message="X", user_id="u1", **_CRON)
        assert len(engine.list_jobs()) == 2


class TestWebhookUrlValidation:
    """Webhook URL validated at creation and update time."""

    def test_invalid_scheme_rejected(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        with pytest.raises(ValueError, match="http/https"):
            engine.add(name="bad", message="X", user_id="u1",
                       webhook_url="ftp://example.com", **_CRON)

    def test_no_host_rejected(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        with pytest.raises(ValueError, match="valid host"):
            engine.add(name="bad", message="X", user_id="u1",
                       webhook_url="http://", **_CRON)

    def test_valid_url_accepted(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        job = engine.add(name="ok", message="X", user_id="u1",
                         webhook_url="https://example.com/hook", **_CRON)
        assert job.webhook_url == "https://example.com/hook"

    def test_empty_url_accepted(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        job = engine.add(name="no_wh", message="X", user_id="u1", **_CRON)
        assert job.webhook_url == ""

    def test_update_invalid_webhook_rejected(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        job = engine.add(name="upd", message="X", user_id="u1", **_CRON)
        with pytest.raises(ValueError, match="http/https"):
            engine.update(job.id, webhook_url="ftp://bad.com")


class TestEnumValidation:
    """Enum fields validated at creation and from_dict."""

    def test_invalid_type_rejected(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        with pytest.raises(ValueError, match="Invalid type"):
            engine.add(name="bad", message="X", user_id="u1",
                       cron_type="nonexistent", cron="0 9 * * *")

    def test_invalid_delivery_mode_rejected(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        with pytest.raises(ValueError, match="Invalid delivery_mode"):
            engine.add(name="bad", message="X", user_id="u1",
                       delivery_mode="carrier_pigeon", **_CRON)

    def test_invalid_session_mode_rejected(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        with pytest.raises(ValueError, match="Invalid session_mode"):
            engine.add(name="bad", message="X", user_id="u1",
                       session_mode="telepathy", **_CRON)

    def test_invalid_misfire_policy_rejected(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        with pytest.raises(ValueError, match="Invalid misfire_policy"):
            engine.add(name="bad", message="X", user_id="u1",
                       misfire_policy="panic", **_CRON)

    def test_from_dict_invalid_type_rejected(self):
        from posipaka.core.cron_engine import CronJob
        with pytest.raises(ValueError, match="Invalid type"):
            CronJob.from_dict({
                "id": "abc", "name": "t", "type": "bogus",
                "message": "X", "user_id": "u1",
            })

    def test_update_invalid_enum_rejected(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        job = engine.add(name="e", message="X", user_id="u1", **_CRON)
        with pytest.raises(ValueError, match="Invalid delivery_mode"):
            engine.update(job.id, delivery_mode="bad_value")

    def test_valid_enums_accepted(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        job = engine.add(
            name="good", message="X", user_id="u1",
            cron_type="recurring", cron="0 9 * * *",
            delivery_mode="webhook", session_mode="custom",
            misfire_policy="skip", webhook_url="https://example.com",
        )
        assert job.delivery_mode == "webhook"
        assert job.session_mode == "custom"
        assert job.misfire_policy == "skip"


class TestUpdatedAtReadonly:
    """updated_at cannot be set via update()."""

    def test_updated_at_rejected(self, tmp_path):
        engine = CronEngine(tmp_path / "cron")
        engine.init()
        job = engine.add(name="ts", message="X", user_id="u1", **_CRON)
        with pytest.raises(ValueError, match="readonly"):
            engine.update(job.id, updated_at="2020-01-01T00:00:00")


class TestCronParserEveryHour:
    """Parser handles 'every hour' / 'щогодини' / 'каждый час'."""

    def test_every_hour_en(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("every hour")
        assert result.is_valid
        assert result.cron_type == CronType.INTERVAL
        assert result.every == "1h"

    def test_hourly_en(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("hourly")
        assert result.is_valid
        assert result.every == "1h"

    def test_every_hour_ua(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("щогодини")
        assert result.is_valid
        assert result.every == "1h"

    def test_every_hour_ru(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("каждый час")
        assert result.is_valid
        assert result.every == "1h"

    def test_every_minute_en(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("every minute")
        assert result.is_valid
        assert result.every == "1m"

    def test_minutely_en(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("minutely")
        assert result.is_valid
        assert result.every == "1m"

    def test_every_minute_ua(self):
        from posipaka.core.cron_parser import parse_schedule
        result = parse_schedule("щохвилини")
        assert result.is_valid
        assert result.every == "1m"
