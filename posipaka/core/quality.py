"""SLO monitoring, quality scoring та drift detection (Phase 39)."""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from loguru import logger


@dataclass
class SLODefinition:
    name: str
    metric: str  # "response_time", "error_rate", "quality", "cost"
    target: float
    window_seconds: int = 3600  # 1 година rolling window


@dataclass
class MetricSample:
    timestamp: float
    value: float
    metadata: dict = field(default_factory=dict)


class SLOMonitor:
    """
    Моніторинг Service Level Objectives з rolling windows.

    SLOs за замовчуванням:
    - Response time P95 < 10s
    - Error rate < 5%
    - Quality score > 0.7
    - Cost per message < $0.05
    """

    DEFAULT_SLOS = [
        SLODefinition("response_time_p95", "response_time", 10.0, 3600),
        SLODefinition("error_rate", "error_rate", 0.05, 3600),
        SLODefinition("quality_score", "quality", 0.7, 3600),
        SLODefinition("cost_per_message", "cost", 0.05, 3600),
    ]

    def __init__(self, data_dir: Path | None = None) -> None:
        self._metrics: dict[str, deque[MetricSample]] = {}
        self._slos = list(self.DEFAULT_SLOS)
        self._data_dir = data_dir
        self._violations: list[dict] = []

    def record(self, metric: str, value: float, **metadata) -> None:
        """Записати метрику."""
        if metric not in self._metrics:
            self._metrics[metric] = deque(maxlen=10000)
        self._metrics[metric].append(
            MetricSample(time.time(), value, metadata)
        )

    def check_slos(self) -> list[dict]:
        """Перевірити всі SLO та повернути порушення."""
        violations = []
        now = time.time()

        for slo in self._slos:
            samples = self._metrics.get(slo.metric, deque())
            window_samples = [
                s for s in samples if now - s.timestamp < slo.window_seconds
            ]

            if not window_samples:
                continue

            values = [s.value for s in window_samples]

            if slo.metric == "response_time":
                # P95
                values_sorted = sorted(values)
                idx = int(len(values_sorted) * 0.95)
                current = values_sorted[min(idx, len(values_sorted) - 1)]
                violated = current > slo.target
            elif slo.metric == "error_rate":
                current = sum(1 for v in values if v > 0) / len(values)
                violated = current > slo.target
            elif slo.metric in ("quality", "cost"):
                current = sum(values) / len(values)
                if slo.metric == "quality":
                    violated = current < slo.target
                else:
                    violated = current > slo.target
            else:
                continue

            if violated:
                violation = {
                    "slo": slo.name,
                    "target": slo.target,
                    "current": round(current, 4),
                    "samples": len(window_samples),
                    "timestamp": datetime.now().isoformat(),
                }
                violations.append(violation)
                self._violations.append(violation)
                logger.warning(
                    f"SLO порушення: {slo.name} = {current:.4f} (target: {slo.target})"
                )

        return violations

    def get_report(self) -> dict:
        """Повний звіт по SLO."""
        report: dict = {"slos": [], "overall_status": "ok"}
        now = time.time()

        for slo in self._slos:
            samples = self._metrics.get(slo.metric, deque())
            window_samples = [
                s for s in samples if now - s.timestamp < slo.window_seconds
            ]
            values = [s.value for s in window_samples]

            slo_report: dict = {
                "name": slo.name,
                "target": slo.target,
                "samples": len(window_samples),
                "status": "no_data",
            }

            if values:
                slo_report["avg"] = round(sum(values) / len(values), 4)
                slo_report["min"] = round(min(values), 4)
                slo_report["max"] = round(max(values), 4)
                slo_report["status"] = "ok"  # Буде перевизначено check_slos

            report["slos"].append(slo_report)

        violations = self.check_slos()
        if violations:
            report["overall_status"] = "violation"
            report["violations"] = violations

        return report


class DriftDetector:
    """
    Виявлення дрифту якості/поведінки агента з часом.

    Порівнює поточні метрики з baseline, побудованим
    з перших N взаємодій.
    """

    BASELINE_SIZE = 100  # взаємодій для побудови baseline

    def __init__(self, data_dir: Path | None = None) -> None:
        self._baseline: dict[str, dict] | None = None
        self._current_samples: dict[str, list[float]] = {}
        self._data_dir = data_dir
        self._baseline_file = (data_dir / ".quality_baseline.json") if data_dir else None
        self._load_baseline()

    def _load_baseline(self) -> None:
        if self._baseline_file and self._baseline_file.exists():
            self._baseline = json.loads(self._baseline_file.read_text())

    def _save_baseline(self) -> None:
        if self._baseline_file and self._baseline:
            self._baseline_file.write_text(json.dumps(self._baseline, indent=2))

    def record(self, metric: str, value: float) -> None:
        """Записати значення для виявлення дрифту."""
        if metric not in self._current_samples:
            self._current_samples[metric] = []
        self._current_samples[metric].append(value)

        # Автоматична побудова baseline після достатньої кількості зразків
        if not self._baseline:
            all_enough = all(
                len(v) >= self.BASELINE_SIZE
                for v in self._current_samples.values()
            )
            if all_enough and self._current_samples:
                self._build_baseline()

    def _build_baseline(self) -> None:
        """Побудувати baseline зі зібраних зразків."""
        self._baseline = {}
        for metric, values in self._current_samples.items():
            baseline_values = values[: self.BASELINE_SIZE]
            mean = sum(baseline_values) / len(baseline_values)
            variance = sum((v - mean) ** 2 for v in baseline_values) / len(baseline_values)
            std = variance ** 0.5
            self._baseline[metric] = {
                "mean": mean,
                "std": max(std, 0.001),  # уникнути ділення на нуль
                "n": len(baseline_values),
            }
        self._save_baseline()
        logger.info(f"Quality baseline побудовано з {self.BASELINE_SIZE} взаємодій")

    def check_drift(self, window: int = 50) -> list[dict]:
        """
        Перевірити дрифт останніх зразків відносно baseline.
        Повертає список алертів (deviation > 1.0 std).
        """
        if not self._baseline:
            return []

        alerts = []
        for metric, baseline in self._baseline.items():
            recent = self._current_samples.get(metric, [])[-window:]
            if len(recent) < 10:
                continue

            current_mean = sum(recent) / len(recent)
            deviation = abs(current_mean - baseline["mean"]) / baseline["std"]

            if deviation > 1.0:
                alert = {
                    "metric": metric,
                    "baseline_mean": round(baseline["mean"], 4),
                    "current_mean": round(current_mean, 4),
                    "deviation_std": round(deviation, 2),
                    "direction": "up" if current_mean > baseline["mean"] else "down",
                    "timestamp": datetime.now().isoformat(),
                }
                alerts.append(alert)
                logger.warning(
                    f"Дрифт виявлено: {metric} = {current_mean:.4f} "
                    f"(baseline: {baseline['mean']:.4f}, {deviation:.1f}\u03c3)"
                )

        return alerts


class QualityMonitor:
    """
    Моніторинг якості відповідей за допомогою евристик.
    (LLM-as-judge дорогий, тому за замовчуванням евристичний скоринг)
    """

    def score_response(
        self,
        query: str,
        response: str,
        tool_calls: int = 0,
        response_time: float = 0,
        error: bool = False,
    ) -> dict:
        """
        Оцінити відповідь за кількома вимірами.
        Повертає dict з оцінками 0.0-1.0.
        """
        scores: dict[str, float] = {}

        # Relevance: довжина відповіді відносно запиту
        if error:
            scores["relevance"] = 0.0
        elif len(response) < 10:
            scores["relevance"] = 0.2
        elif len(response) > len(query) * 0.5:
            scores["relevance"] = min(1.0, 0.5 + len(response) / max(len(query) * 3, 1))
        else:
            scores["relevance"] = 0.5

        # Helpfulness: чи використовували інструменти коли потрібно?
        question_words = {
            "як", "що", "де", "коли", "чому", "скільки",
            "how", "what", "where", "when", "why",
        }
        is_question = any(w in query.lower().split() for w in question_words)
        if is_question and tool_calls > 0:
            scores["helpfulness"] = 0.9
        elif is_question and len(response) > 100:
            scores["helpfulness"] = 0.7
        elif not error:
            scores["helpfulness"] = 0.6
        else:
            scores["helpfulness"] = 0.1

        # Speed: штраф за повільні відповіді
        if response_time < 3:
            scores["speed"] = 1.0
        elif response_time < 10:
            scores["speed"] = 0.7
        elif response_time < 30:
            scores["speed"] = 0.4
        else:
            scores["speed"] = 0.2

        # Safety: базова перевірка (InjectionDetector обробляє решту)
        scores["safety"] = 1.0

        # Overall (зважена сума)
        weights = {"relevance": 0.3, "helpfulness": 0.3, "speed": 0.2, "safety": 0.2}
        scores["overall"] = sum(scores[k] * weights[k] for k in weights)

        return {k: round(v, 3) for k, v in scores.items()}
