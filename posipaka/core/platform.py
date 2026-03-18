"""Platform detection та Android/Termux support."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from loguru import logger


@dataclass
class PlatformInfo:
    os_name: str  # "linux", "darwin", "windows"
    is_android: bool
    is_termux: bool
    is_docker: bool
    is_wsl: bool
    cpu_count: int
    ram_mb: int
    python_version: str
    has_gpu: bool = False


def detect_platform() -> PlatformInfo:
    """Визначити платформу та її можливості."""
    os_name = platform.system().lower()
    is_android = _is_android()
    is_termux = "TERMUX_VERSION" in os.environ
    is_docker = Path("/.dockerenv").exists() or _check_cgroup_docker()
    is_wsl = "microsoft" in platform.uname().release.lower()

    # RAM
    ram_mb = _get_ram_mb()

    # GPU
    has_gpu = _check_gpu()

    return PlatformInfo(
        os_name=os_name,
        is_android=is_android,
        is_termux=is_termux,
        is_docker=is_docker,
        is_wsl=is_wsl,
        cpu_count=os.cpu_count() or 1,
        ram_mb=ram_mb,
        python_version=platform.python_version(),
        has_gpu=has_gpu,
    )


def _is_android() -> bool:
    """Перевірити чи працюємо на Android."""
    if "ANDROID_ROOT" in os.environ:
        return True
    if Path("/system/build.prop").exists():
        return True
    return False


def _check_cgroup_docker() -> bool:
    try:
        cgroup = Path("/proc/1/cgroup")
        if cgroup.exists():
            return "docker" in cgroup.read_text()
    except Exception:
        pass
    return False


def _get_ram_mb() -> int:
    try:
        import psutil
        return int(psutil.virtual_memory().total / (1024 * 1024))
    except ImportError:
        pass
    try:
        meminfo = Path("/proc/meminfo").read_text()
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


def _check_gpu() -> bool:
    try:
        result = subprocess.run(
            ["nvidia-smi"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


class BatteryProfile(str, Enum):
    CHARGING = "charging"
    HIGH = "high"        # >60%
    MEDIUM = "medium"    # 30-60%
    LOW = "low"          # 15-30%
    CRITICAL = "critical"  # <15%


class BatteryManager:
    """Управління енергією на Android/laptop."""

    HEARTBEAT_INTERVALS = {
        BatteryProfile.CHARGING: 300,    # 5 min
        BatteryProfile.HIGH: 600,        # 10 min
        BatteryProfile.MEDIUM: 1800,     # 30 min
        BatteryProfile.LOW: 3600,        # 1 hour
        BatteryProfile.CRITICAL: 0,      # disabled
    }

    def get_battery_status(self) -> dict | None:
        """Отримати статус батареї (Android termux-api або psutil)."""
        # Termux
        try:
            result = subprocess.run(
                ["termux-battery-status"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                import json
                return json.loads(result.stdout)
        except Exception:
            pass

        # psutil fallback (laptops)
        try:
            import psutil
            battery = psutil.sensors_battery()
            if battery:
                return {
                    "percentage": battery.percent,
                    "status": "CHARGING" if battery.power_plugged else "DISCHARGING",
                    "plugged": battery.power_plugged,
                }
        except Exception:
            pass

        return None

    def get_profile(self) -> BatteryProfile:
        """Визначити профіль на основі заряду батареї."""
        status = self.get_battery_status()
        if not status:
            return BatteryProfile.HIGH  # No battery = desktop/server

        if status.get("status") == "CHARGING" or status.get("plugged"):
            return BatteryProfile.CHARGING

        level = status.get("percentage", 100)
        if level > 60:
            return BatteryProfile.HIGH
        elif level > 30:
            return BatteryProfile.MEDIUM
        elif level > 15:
            return BatteryProfile.LOW
        else:
            return BatteryProfile.CRITICAL

    def should_throttle(self) -> bool:
        """Чи потрібно знизити навантаження."""
        profile = self.get_profile()
        return profile in (BatteryProfile.LOW, BatteryProfile.CRITICAL)

    def get_heartbeat_interval(self) -> int:
        """Адаптивний інтервал heartbeat на основі батареї."""
        return self.HEARTBEAT_INTERVALS[self.get_profile()]

    def get_recommended_profile(self, ram_mb: int) -> str:
        """Рекомендований resource profile на основі RAM."""
        if ram_mb < 2048:
            return "minimal"
        elif ram_mb < 4096:
            return "standard"
        else:
            return "performance"


class AndroidPlatform:
    """Termux-API інтеграція для Android."""

    @staticmethod
    def send_notification(title: str, text: str) -> bool:
        """Відправити Android сповіщення через termux-notification."""
        try:
            result = subprocess.run(
                ["termux-notification", "--title", title, "--content", text],
                capture_output=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def speak(text: str) -> bool:
        """TTS через termux-tts-speak."""
        try:
            result = subprocess.run(
                ["termux-tts-speak", text],
                capture_output=True, timeout=30,
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def get_location() -> dict | None:
        """Отримати GPS координати."""
        try:
            result = subprocess.run(
                ["termux-location", "-p", "network", "-r", "once"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                import json
                return json.loads(result.stdout)
        except Exception:
            pass
        return None
