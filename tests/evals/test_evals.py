"""Тести для eval sets — регресійне тестування якості та безпеки."""

from __future__ import annotations

import pytest

from tests.evals.eval_runner import EvalRunner


@pytest.fixture
def runner():
    return EvalRunner()


def test_safety_evals(runner):
    """Всі injection patterns мають бути заблоковані."""
    result = runner.run_safety_evals()
    assert result.pass_rate == 1.0, (
        f"Safety evals: {result.passed}/{result.total}. Failed: {result.details}"
    )


def test_clean_input_evals(runner):
    """Чисті повідомлення не мають бути заблоковані (false positive)."""
    result = runner.run_clean_input_evals()
    assert result.pass_rate == 1.0, (
        f"Clean input evals: {result.passed}/{result.total}. False positives: {result.details}"
    )


def test_sandbox_evals(runner):
    """Деструктивні команди мають бути заблоковані."""
    result = runner.run_sandbox_evals()
    assert result.pass_rate == 1.0, (
        f"Sandbox evals: {result.passed}/{result.total}. Failed: {result.details}"
    )


def test_model_routing_evals(runner):
    """Прості запити → fast model, складні → complex."""
    result = runner.run_model_routing_evals()
    assert result.pass_rate >= 0.75, (
        f"Model routing: {result.passed}/{result.total}. Failed: {result.details}"
    )


def test_run_all_evals(runner):
    """Інтегральний тест — всі eval sets."""
    results = runner.run_all()
    total = sum(r.total for r in results)
    passed = sum(r.passed for r in results)
    assert passed / total >= 0.9, f"Overall: {passed}/{total}"
