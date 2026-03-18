"""Lightweight built-in metrics system (MASTER.md sec 86.10).

Prometheus-compatible text exposition format export,
zero external dependencies beyond stdlib + loguru.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger

# ── Enums ──────────────────────────────────────────────────────


class MetricType(Enum):
    """Supported metric types."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


# ── Dataclasses ────────────────────────────────────────────────


@dataclass
class Metric:
    """Single metric snapshot."""

    name: str
    metric_type: MetricType
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class _HistogramState:
    """Internal state for a histogram metric."""

    count: int = 0
    total: float = 0.0
    buckets: dict[float, int] = field(default_factory=dict)


# ── Default histogram buckets ──────────────────────────────────

DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25,
    0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0,
)


def _labels_key(labels: dict[str, str] | None) -> str:
    """Serialize labels dict into a stable hashable string."""
    if not labels:
        return ""
    pairs = sorted(labels.items())
    return ",".join(f'{k}="{v}"' for k, v in pairs)


def _prom_labels(labels: dict[str, str]) -> str:
    """Format labels for Prometheus text exposition."""
    if not labels:
        return ""
    pairs = sorted(labels.items())
    inner = ",".join(f'{k}="{v}"' for k, v in pairs)
    return "{" + inner + "}"


# ── MetricsRegistry ───────────────────────────────────────────


class MetricsRegistry:
    """
    Thread-safe in-process metrics registry.

    Supports counters, gauges, and histograms.
    Exports to Prometheus text format and JSON.
    """

    def __init__(
        self,
        histogram_buckets: tuple[float, ...] = DEFAULT_BUCKETS,
    ) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[str, float]] = {}
        self._gauges: dict[str, dict[str, float]] = {}
        self._histograms: dict[
            str, dict[str, _HistogramState]
        ] = {}
        self._buckets = histogram_buckets
        logger.debug("MetricsRegistry initialized")

    # ── Counter ────────────────────────────────────────────

    def counter(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        increment: float = 1.0,
    ) -> None:
        """Increment a counter metric."""
        key = _labels_key(labels)
        with self._lock:
            if name not in self._counters:
                self._counters[name] = {}
            self._counters[name].setdefault(key, 0.0)
            self._counters[name][key] += increment

    # ── Gauge ──────────────────────────────────────────────

    def gauge(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Set a gauge metric to the given value."""
        key = _labels_key(labels)
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = {}
            self._gauges[name][key] = value

    # ── Histogram ──────────────────────────────────────────

    def histogram(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Record an observation in a histogram."""
        key = _labels_key(labels)
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = {}
            if key not in self._histograms[name]:
                self._histograms[name][key] = _HistogramState(
                    buckets={b: 0 for b in self._buckets},
                )
            state = self._histograms[name][key]
            state.count += 1
            state.total += value
            for b in self._buckets:
                if value <= b:
                    state.buckets[b] += 1

    # ── Query ──────────────────────────────────────────────

    def get_all(self) -> list[Metric]:
        """Return snapshot of all metrics as Metric objects."""
        now = time.time()
        result: list[Metric] = []
        with self._lock:
            for name, series in self._counters.items():
                for lk, val in series.items():
                    result.append(Metric(
                        name=name,
                        metric_type=MetricType.COUNTER,
                        value=val,
                        labels=_parse_labels(lk),
                        timestamp=now,
                    ))
            for name, series in self._gauges.items():
                for lk, val in series.items():
                    result.append(Metric(
                        name=name,
                        metric_type=MetricType.GAUGE,
                        value=val,
                        labels=_parse_labels(lk),
                        timestamp=now,
                    ))
            for name, series in self._histograms.items():
                for lk, state in series.items():
                    result.append(Metric(
                        name=name,
                        metric_type=MetricType.HISTOGRAM,
                        value=state.total,
                        labels=_parse_labels(lk),
                        timestamp=now,
                    ))
        return result

    # ── Prometheus export ──────────────────────────────────

    def export_prometheus(self) -> str:
        """Export all metrics in Prometheus text exposition format."""
        lines: list[str] = []
        with self._lock:
            # Counters
            for name, series in sorted(self._counters.items()):
                lines.append(f"# HELP {name} counter")
                lines.append(f"# TYPE {name} counter")
                for lk, val in sorted(series.items()):
                    lbl = _prom_labels(_parse_labels(lk))
                    lines.append(f"{name}{lbl} {_fmt(val)}")

            # Gauges
            for name, series in sorted(self._gauges.items()):
                lines.append(f"# HELP {name} gauge")
                lines.append(f"# TYPE {name} gauge")
                for lk, val in sorted(series.items()):
                    lbl = _prom_labels(_parse_labels(lk))
                    lines.append(f"{name}{lbl} {_fmt(val)}")

            # Histograms
            for name, series in sorted(
                self._histograms.items()
            ):
                lines.append(f"# HELP {name} histogram")
                lines.append(f"# TYPE {name} histogram")
                for lk, state in sorted(series.items()):
                    labels = _parse_labels(lk)
                    cumulative = 0
                    for b in sorted(state.buckets):
                        cumulative += state.buckets[b]
                        bl = {**labels, "le": _fmt(b)}
                        lbl = _prom_labels(bl)
                        lines.append(
                            f"{name}_bucket{lbl} {cumulative}"
                        )
                    # +Inf bucket
                    bl_inf = {**labels, "le": "+Inf"}
                    lbl_inf = _prom_labels(bl_inf)
                    lines.append(
                        f"{name}_bucket{lbl_inf}"
                        f" {state.count}"
                    )
                    # sum and count
                    lbl = _prom_labels(labels)
                    lines.append(
                        f"{name}_sum{lbl} {_fmt(state.total)}"
                    )
                    lines.append(
                        f"{name}_count{lbl} {state.count}"
                    )

        lines.append("")
        return "\n".join(lines)

    # ── JSON export ────────────────────────────────────────

    def export_json(self) -> dict[str, Any]:
        """Export all metrics as a JSON-serializable dict."""
        data: dict[str, Any] = {
            "timestamp": time.time(),
            "counters": {},
            "gauges": {},
            "histograms": {},
        }
        with self._lock:
            for name, series in self._counters.items():
                data["counters"][name] = [
                    {
                        "labels": _parse_labels(lk),
                        "value": val,
                    }
                    for lk, val in series.items()
                ]
            for name, series in self._gauges.items():
                data["gauges"][name] = [
                    {
                        "labels": _parse_labels(lk),
                        "value": val,
                    }
                    for lk, val in series.items()
                ]
            for name, series in self._histograms.items():
                data["histograms"][name] = [
                    {
                        "labels": _parse_labels(lk),
                        "count": state.count,
                        "sum": state.total,
                        "buckets": {
                            str(b): state.buckets[b]
                            for b in sorted(state.buckets)
                        },
                    }
                    for lk, state in series.items()
                ]
        return data

    # ── Reset ──────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all recorded metrics."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
        logger.info("MetricsRegistry reset")


# ── Default metric names ──────────────────────────────────────

MESSAGES_TOTAL = "posipaka_messages_total"
LLM_CALLS_TOTAL = "posipaka_llm_calls_total"
LLM_LATENCY_SECONDS = "posipaka_llm_latency_seconds"
TOOL_CALLS_TOTAL = "posipaka_tool_calls_total"
ERRORS_TOTAL = "posipaka_errors_total"
ACTIVE_SESSIONS = "posipaka_active_sessions"
COST_USD_TOTAL = "posipaka_cost_usd_total"
MEMORY_USAGE_BYTES = "posipaka_memory_usage_bytes"


# ── Helper: record_llm_call ──────────────────────────────────


def record_llm_call(
    registry: MetricsRegistry,
    model: str,
    latency: float,
    tokens: int,
    cost: float,
) -> None:
    """
    Convenience helper — records multiple metrics for one LLM call.

    Args:
        registry: MetricsRegistry instance.
        model: Model name (e.g. "claude-opus-4-6").
        latency: Request duration in seconds.
        tokens: Total tokens consumed (input + output).
        cost: Cost in USD.
    """
    labels = {"model": model}
    registry.counter(LLM_CALLS_TOTAL, labels)
    registry.histogram(LLM_LATENCY_SECONDS, latency, labels)
    registry.counter(COST_USD_TOTAL, increment=cost)
    logger.debug(
        "LLM call recorded: model={} latency={:.3f}s "
        "tokens={} cost=${:.6f}",
        model, latency, tokens, cost,
    )


# ── Singleton global registry ─────────────────────────────────

_global_registry: MetricsRegistry | None = None


def get_metrics_registry() -> MetricsRegistry:
    """Return the global MetricsRegistry singleton."""
    global _global_registry
    if _global_registry is None:
        _global_registry = MetricsRegistry()
    return _global_registry


# ── Internal helpers ──────────────────────────────────────────


def _parse_labels(key: str) -> dict[str, str]:
    """Parse a labels key back into a dict."""
    if not key:
        return {}
    result: dict[str, str] = {}
    for pair in key.split(","):
        k, v = pair.split("=", 1)
        result[k] = v.strip('"')
    return result


def _fmt(value: float) -> str:
    """Format a float for Prometheus output."""
    if value == float("inf"):
        return "+Inf"
    if value == float("-inf"):
        return "-Inf"
    if math.isnan(value):
        return "NaN"
    if value == int(value):
        return str(int(value))
    return f"{value:.6g}"
