"""Тести для CronEngine."""

from __future__ import annotations

import pytest

from posipaka.core.cron_engine import CronEngine, CronType


@pytest.fixture
def engine(tmp_path):
    cron_dir = tmp_path / "cron"
    engine = CronEngine(cron_dir)
    engine.init()
    return engine


def test_add_and_list(engine):
    engine.add(
        name="test_job",
        message="Hello",
        user_id="u1",
        cron_type=CronType.RECURRING,
        cron="0 9 * * *",
    )
    jobs = engine.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["name"] == "test_job"
    assert jobs[0]["schedule"] == "0 9 * * *"


def test_persistence(tmp_path):
    """Jobs відновлюються після рестарту."""
    cron_dir = tmp_path / "cron"
    engine1 = CronEngine(cron_dir)
    engine1.init()
    engine1.add(name="persistent", message="Hi", user_id="u1")

    # New engine instance
    engine2 = CronEngine(cron_dir)
    engine2.init()
    assert len(engine2.list_jobs()) == 1
    assert engine2.list_jobs()[0]["name"] == "persistent"


def test_remove_by_name(engine):
    engine.add(name="removable", message="Bye", user_id="u1")
    assert engine.remove("removable") is True
    assert len(engine.list_jobs()) == 0


def test_enable_disable(engine):
    job = engine.add(name="toggle", message="X", user_id="u1")
    engine.disable(job.id)
    assert engine.get(job.id).enabled is False
    engine.enable(job.id)
    assert engine.get(job.id).enabled is True


def test_mark_run_and_delete(engine):
    job = engine.add(
        name="once",
        message="One time",
        user_id="u1",
        cron_type=CronType.ONE_SHOT,
        at="2026-04-01T09:00:00",
        delete_after_run=True,
    )
    engine.mark_run(job.id)
    assert len(engine.list_jobs()) == 0


def test_parse_every():
    assert CronEngine.parse_every("30m") == 1800
    assert CronEngine.parse_every("4h") == 14400
    assert CronEngine.parse_every("1d") == 86400
