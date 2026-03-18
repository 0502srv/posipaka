"""Тести для CostGuard."""

from __future__ import annotations

from posipaka.core.cost_guard import CostGuard


def test_cost_guard_allows_normal_request():
    guard = CostGuard(daily_budget_usd=5.0, per_request_max_usd=0.50)
    allowed, reason = guard.check_before_call(
        model="claude-sonnet-4-20250514",
        estimated_input_tokens=1000,
        session_id="test",
        max_output_tokens=1000,
    )
    assert allowed is True
    assert reason == "ok"


def test_cost_guard_blocks_expensive_request():
    guard = CostGuard(daily_budget_usd=5.0, per_request_max_usd=0.01)
    allowed, reason = guard.check_before_call(
        model="claude-opus-4-20250514",
        estimated_input_tokens=10000,
        session_id="test",
        max_output_tokens=4096,
    )
    assert allowed is False
    assert "ліміт запиту" in reason


def test_cost_guard_blocks_after_budget_exhausted():
    guard = CostGuard(daily_budget_usd=0.01)
    guard.record("claude-sonnet-4-20250514", 5000, 2000, "test")
    allowed, reason = guard.check_before_call(
        model="claude-sonnet-4-20250514",
        estimated_input_tokens=1000,
        session_id="test",
    )
    assert allowed is False
    assert "бюджет" in reason.lower()


def test_cost_guard_daily_report():
    guard = CostGuard(daily_budget_usd=5.0)
    guard.record("claude-sonnet-4-20250514", 1000, 500, "s1")
    report = guard.get_daily_report()
    assert "Витрачено" in report
    assert "Запитів: 1" in report


def test_cost_guard_session_limit():
    guard = CostGuard(per_session_max_usd=0.001)
    guard.record("claude-sonnet-4-20250514", 5000, 2000, "session1")
    allowed, reason = guard.check_before_call(
        model="claude-sonnet-4-20250514",
        estimated_input_tokens=1000,
        session_id="session1",
    )
    assert allowed is False
    assert "сесії" in reason.lower()
