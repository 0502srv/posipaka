"""Resource Monitor з auto-optimization."""

from __future__ import annotations

import gc
from dataclasses import dataclass

from loguru import logger

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]


@dataclass
class ResourceSnapshot:
    cpu_percent: float
    memory_used_mb: float
    memory_total_mb: float
    memory_percent: float
    disk_used_gb: float
    disk_free_gb: float
    disk_percent: float
    open_files: int
    active_threads: int
    temperature: float | None = None


class ResourceMonitor:
    """Моніторинг ресурсів з автоматичною оптимізацією."""

    RAM_WARNING = 70.0
    RAM_CRITICAL = 85.0
    CPU_WARNING = 80.0
    DISK_WARNING = 85.0

    def snapshot(self) -> ResourceSnapshot:
        """Зібрати поточний стан ресурсів."""
        if psutil is None:
            return ResourceSnapshot(
                cpu_percent=0, memory_used_mb=0, memory_total_mb=0,
                memory_percent=0, disk_used_gb=0, disk_free_gb=0,
                disk_percent=0, open_files=0, active_threads=1,
            )

        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        proc = psutil.Process()

        temp = None
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                first = list(temps.values())[0]
                if first:
                    temp = first[0].current
        except (AttributeError, Exception):
            pass

        return ResourceSnapshot(
            cpu_percent=psutil.cpu_percent(interval=0.1),
            memory_used_mb=mem.used / (1024 * 1024),
            memory_total_mb=mem.total / (1024 * 1024),
            memory_percent=mem.percent,
            disk_used_gb=disk.used / (1024**3),
            disk_free_gb=disk.free / (1024**3),
            disk_percent=disk.percent,
            open_files=len(proc.open_files()),
            active_threads=proc.num_threads(),
            temperature=temp,
        )

    def analyze_and_optimize(self) -> list[str]:
        """Аналіз та автоматична оптимізація."""
        snap = self.snapshot()
        actions = []

        # RAM optimization
        if snap.memory_percent >= self.RAM_CRITICAL:
            gc.collect()
            actions.append("gc.collect() — RAM critical")
            logger.warning(f"RAM critical: {snap.memory_percent:.1f}%")
        elif snap.memory_percent >= self.RAM_WARNING:
            gc.collect()
            actions.append("gc.collect() — RAM warning")

        # CPU warning
        if snap.cpu_percent >= self.CPU_WARNING:
            actions.append(f"CPU high: {snap.cpu_percent:.1f}% — consider throttling")
            logger.warning(f"CPU high: {snap.cpu_percent:.1f}%")

        # Disk warning
        if snap.disk_percent >= self.DISK_WARNING:
            actions.append(f"Disk space low: {snap.disk_free_gb:.1f}GB free — cleanup recommended")
            logger.warning(f"Disk: {snap.disk_percent:.1f}% used, {snap.disk_free_gb:.1f}GB free")

        return actions

    def get_status_report(self) -> str:
        """Форматований звіт для CLI/Telegram."""
        snap = self.snapshot()

        def bar(percent: float, width: int = 20) -> str:
            filled = int(width * min(percent, 100) / 100)
            return f"[{'█' * filled}{'░' * (width - filled)}]"

        lines = [
            "System Resources",
            "─" * 40,
            f"CPU:  {bar(snap.cpu_percent)} {snap.cpu_percent:5.1f}%",
            f"RAM:  {bar(snap.memory_percent)} {snap.memory_percent:5.1f}% "
            f"({snap.memory_used_mb:.0f}/{snap.memory_total_mb:.0f} MB)",
            f"Disk: {bar(snap.disk_percent)} {snap.disk_percent:5.1f}% "
            f"({snap.disk_free_gb:.1f} GB free)",
            f"Files: {snap.open_files} open | Threads: {snap.active_threads}",
        ]

        if snap.temperature is not None:
            lines.append(f"Temp: {snap.temperature:.1f}°C")

        # Warnings
        if snap.memory_percent >= self.RAM_CRITICAL:
            lines.append("⚠ RAM CRITICAL — auto-optimization active")
        elif snap.memory_percent >= self.RAM_WARNING:
            lines.append("⚠ RAM high — monitoring")

        if snap.disk_percent >= self.DISK_WARNING:
            lines.append("⚠ Disk space low — cleanup recommended")

        return "\n".join(lines)
