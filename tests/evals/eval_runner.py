"""Eval runner — запуск eval sets і агрегація результатів."""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from posipaka.core.model_router import ModelRouter
from posipaka.security.injection import InjectionDetector
from posipaka.security.sandbox import ShellSandbox

from .eval_sets import (
    CLEAN_INPUT_EVALS,
    MODEL_ROUTING_EVALS,
    SAFETY_EVALS,
    SANDBOX_EVALS,
)


@dataclass
class EvalResult:
    set_name: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    details: list[dict] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total > 0 else 0.0

    def summary(self) -> str:
        pct = self.pass_rate * 100
        status = "PASS" if pct == 100 else "FAIL"
        return f"[{status}] {self.set_name}: {self.passed}/{self.total} ({pct:.0f}%)"


class EvalRunner:
    """Запуск eval sets."""

    def __init__(self) -> None:
        self._detector = InjectionDetector()
        self._sandbox = ShellSandbox()
        self._router = ModelRouter()

    def run_safety_evals(self) -> EvalResult:
        """Перевірити injection detection."""
        result = EvalResult(set_name="safety")
        for case in SAFETY_EVALS:
            result.total += 1
            risk = self._detector.check(case["input"], context=case.get("context", "email_body"))
            expected_blocked = case["expected"] == "blocked"
            actual_blocked = risk.is_dangerous

            if expected_blocked == actual_blocked:
                result.passed += 1
            else:
                result.failed += 1
                result.details.append(
                    {
                        "input": case["input"][:50],
                        "expected": case["expected"],
                        "actual": "blocked" if actual_blocked else "not_blocked",
                        "score": risk.score,
                    }
                )
        return result

    def run_clean_input_evals(self) -> EvalResult:
        """Перевірити false positive rate."""
        result = EvalResult(set_name="clean_inputs")
        for case in CLEAN_INPUT_EVALS:
            result.total += 1
            risk = self._detector.check(case["input"])
            if not risk.is_dangerous:
                result.passed += 1
            else:
                result.failed += 1
                result.details.append(
                    {
                        "input": case["input"],
                        "score": risk.score,
                        "reasons": risk.reasons,
                    }
                )
        return result

    def run_sandbox_evals(self) -> EvalResult:
        """Перевірити ShellSandbox."""
        result = EvalResult(set_name="sandbox")
        for case in SANDBOX_EVALS:
            result.total += 1
            safe, reason = self._sandbox.check_command(case["command"])
            expected_blocked = case["expected"] == "blocked"
            actual_blocked = not safe

            if expected_blocked == actual_blocked:
                result.passed += 1
            else:
                result.failed += 1
                result.details.append(
                    {
                        "command": case["command"],
                        "expected": case["expected"],
                        "actual": "blocked" if actual_blocked else "allowed",
                    }
                )
        return result

    def run_model_routing_evals(self) -> EvalResult:
        """Перевірити ModelRouter."""
        result = EvalResult(set_name="model_routing")
        for case in MODEL_ROUTING_EVALS:
            result.total += 1
            selected = self._router.select(case["input"])

            if case["expected_tier"] == "fast":
                ok = selected == self._router.fast_model
            elif case["expected_tier"] == "complex":
                ok = selected == self._router.complex_model
            else:
                ok = selected == self._router.default_model

            if ok:
                result.passed += 1
            else:
                result.failed += 1
                result.details.append(
                    {
                        "input": case["input"],
                        "expected_tier": case["expected_tier"],
                        "selected_model": selected,
                    }
                )
        return result

    def run_all(self) -> list[EvalResult]:
        """Запустити всі eval sets."""
        results = [
            self.run_safety_evals(),
            self.run_clean_input_evals(),
            self.run_sandbox_evals(),
            self.run_model_routing_evals(),
        ]

        for r in results:
            logger.info(r.summary())
            for detail in r.details:
                logger.warning(f"  FAILED: {detail}")

        total = sum(r.total for r in results)
        passed = sum(r.passed for r in results)
        logger.info(f"TOTAL: {passed}/{total} ({passed / total * 100:.0f}%)")

        return results
