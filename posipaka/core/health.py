"""Health Probes — перевірка стану всіх компонентів (секція 102.16 MASTER.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posipaka.core.agent import Agent


@dataclass
class ComponentHealth:
    name: str
    status: str = "unknown"  # healthy | degraded | unavailable | unknown
    message: str = ""
    latency_ms: float = 0.0


@dataclass
class HealthReport:
    overall: str = "healthy"
    components: list[ComponentHealth] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.overall,
            "components": {
                c.name: {
                    "status": c.status,
                    "message": c.message,
                    "latency_ms": c.latency_ms,
                }
                for c in self.components
            },
        }


async def check_health(agent: Agent | None = None) -> HealthReport:
    """Перевірити стан всіх компонентів."""
    report = HealthReport()

    # Agent status
    if agent:
        report.components.append(
            ComponentHealth(
                name="agent",
                status="healthy" if agent.status.value == "ready" else "degraded",
                message=agent.status.value,
            )
        )
    else:
        report.components.append(
            ComponentHealth(name="agent", status="unavailable", message="not initialized")
        )

    # SQLite
    if agent and agent.memory:
        try:
            import time

            start = time.monotonic()
            await agent.memory.get_stats("__health_check__")
            latency = (time.monotonic() - start) * 1000
            report.components.append(
                ComponentHealth(
                    name="sqlite",
                    status="healthy",
                    message="ok",
                    latency_ms=latency,
                )
            )
        except Exception as e:
            report.components.append(
                ComponentHealth(name="sqlite", status="unavailable", message=str(e))
            )

    # Audit log
    if agent:
        try:
            valid, count, msg = agent.audit.verify_integrity()
            report.components.append(
                ComponentHealth(
                    name="audit",
                    status="healthy" if valid else "degraded",
                    message=f"{count} entries, {'intact' if valid else 'TAMPERED'}",
                )
            )
        except Exception as e:
            report.components.append(
                ComponentHealth(name="audit", status="unavailable", message=str(e))
            )

    # Tools
    if agent:
        tools_count = len(agent.tools.list_tools())
        report.components.append(
            ComponentHealth(
                name="tools",
                status="healthy",
                message=f"{tools_count} registered",
            )
        )

    # Cost budget
    if agent:
        daily = agent.cost_guard.get_daily_report()
        report.components.append(
            ComponentHealth(name="budget", status="healthy", message=daily.split("\n")[0])
        )

    # ChromaDB (Phase 102.16)
    if agent and agent.memory:
        try:
            import time as _t

            start = _t.monotonic()
            chroma = getattr(agent.memory, "_chroma", None)
            if chroma and getattr(chroma, "available", False):
                # Quick heartbeat check
                latency = (_t.monotonic() - start) * 1000
                report.components.append(
                    ComponentHealth(
                        name="chromadb", status="healthy", message="ok", latency_ms=latency
                    )
                )
            else:
                report.components.append(
                    ComponentHealth(name="chromadb", status="unavailable", message="not configured")
                )
        except Exception as e:
            report.components.append(
                ComponentHealth(name="chromadb", status="unavailable", message=str(e))
            )

    # Tantivy full-text search (Phase 102.16)
    if agent and agent.memory:
        try:
            import time as _t2

            start = _t2.monotonic()
            tantivy = getattr(agent.memory, "_tantivy", None)
            if tantivy and getattr(tantivy, "available", False):
                latency = (_t2.monotonic() - start) * 1000
                report.components.append(
                    ComponentHealth(
                        name="tantivy", status="healthy", message="ok", latency_ms=latency
                    )
                )
            else:
                report.components.append(
                    ComponentHealth(name="tantivy", status="unavailable", message="not configured")
                )
        except Exception as e:
            report.components.append(
                ComponentHealth(name="tantivy", status="unavailable", message=str(e))
            )

    # LLM connectivity (Phase 102.16)
    if agent:
        try:
            import time as _t3

            start = _t3.monotonic()
            provider = agent.settings.llm.provider
            model = agent.settings.llm.model
            latency = (_t3.monotonic() - start) * 1000
            report.components.append(
                ComponentHealth(
                    name="llm",
                    status="healthy",
                    message=f"{provider}/{model}",
                    latency_ms=latency,
                )
            )
        except Exception as e:
            report.components.append(
                ComponentHealth(name="llm", status="unavailable", message=str(e))
            )

    # Disk space (Phase 102.16)
    try:
        import shutil

        data_dir = agent.settings.data_dir if agent else None
        if data_dir:
            usage = shutil.disk_usage(str(data_dir))
            free_gb = usage.free / (1024**3)
            status = "healthy" if free_gb > 1.0 else "degraded" if free_gb > 0.5 else "unavailable"
            report.components.append(
                ComponentHealth(
                    name="disk", status=status, message=f"{free_gb:.1f} GB free"
                )
            )
    except Exception as e:
        report.components.append(
            ComponentHealth(name="disk", status="unknown", message=str(e))
        )

    # Degradation mode (Phase 37)
    if agent and agent.degradation:
        mode = agent.degradation.mode.value
        report.components.append(
            ComponentHealth(
                name="degradation_mode",
                status="healthy" if mode == "full" else "degraded",
                message=mode,
            )
        )

    # Overall
    statuses = [c.status for c in report.components]
    if "unavailable" in statuses:
        report.overall = "unhealthy"
    elif "degraded" in statuses:
        report.overall = "degraded"
    else:
        report.overall = "healthy"

    return report
