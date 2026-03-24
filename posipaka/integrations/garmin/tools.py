"""Garmin Connect integration — daily health metrics.

Ported from molt-bot. Requires: pip install garminconnect
Credentials: ~/.posipaka/garmin_credentials.json
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

_TZ = ZoneInfo("Europe/Kyiv")
_CREDS_PATH = Path.home() / ".posipaka" / "garmin_credentials.json"
_DATA_DIR = Path.home() / ".posipaka" / "health" / "garmin"


def _get_client():
    """Authenticate with Garmin Connect."""
    try:
        from garminconnect import Garmin
    except ImportError:
        return None

    if not _CREDS_PATH.exists():
        return None

    creds = json.loads(_CREDS_PATH.read_text())
    client = Garmin(creds.get("email", ""), creds.get("password", ""))
    client.login()
    return client


def _safe_get(func, *args, default=None):
    """Safe API call with fallback."""
    try:
        return func(*args) or default
    except Exception as e:
        logger.debug(f"Garmin API: {e}")
        return default


async def get_garmin_daily(date_str: str = "") -> str:
    """Отримати щоденні метрики Garmin (сон, HR, HRV, стрес, батарейка, готовність).

    date_str: YYYY-MM-DD або порожньо для сьогодні.
    """
    import asyncio

    client = await asyncio.to_thread(_get_client)
    if not client:
        return "Garmin не налаштований. Додайте ~/.posipaka/garmin_credentials.json"

    if not date_str:
        date_str = datetime.now(_TZ).strftime("%Y-%m-%d")

    data = await asyncio.to_thread(_fetch_all, client, date_str)

    # Save to file
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    data_file = _DATA_DIR / f"{date_str}.json"
    data_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    return _format_summary(data, date_str)


def _fetch_all(client, date_str: str) -> dict:
    """Fetch all 9 metrics from Garmin."""
    data = {"date": date_str, "metrics": {}}
    m = data["metrics"]

    # Sleep
    sleep_data = _safe_get(client.get_sleep_data, date_str, default={})
    daily_sleep = sleep_data.get("dailySleepDTO", {})
    if daily_sleep:
        m["sleep"] = {
            "duration_hours": round(daily_sleep.get("sleepTimeSeconds", 0) / 3600, 1),
            "deep_hours": round(daily_sleep.get("deepSleepSeconds", 0) / 3600, 1),
            "light_hours": round(daily_sleep.get("lightSleepSeconds", 0) / 3600, 1),
            "rem_hours": round(daily_sleep.get("remSleepSeconds", 0) / 3600, 1),
            "awake_hours": round(daily_sleep.get("awakeSleepSeconds", 0) / 3600, 1),
            "score": daily_sleep.get("sleepScores", {}).get("overall", {}).get("value", 0),
        }

    # Heart Rate
    hr_data = _safe_get(client.get_heart_rates, date_str, default={})
    if hr_data:
        m["heart_rate"] = {
            "resting": hr_data.get("restingHeartRate", 0),
            "min": hr_data.get("minHeartRate", 0),
            "max": hr_data.get("maxHeartRate", 0),
        }

    # HRV
    hrv_data = _safe_get(client.get_hrv_data, date_str, default={})
    if hrv_data:
        summary = hrv_data.get("hrvSummary", {})
        m["hrv"] = {
            "weekly_avg": summary.get("weeklyAvg", 0),
            "last_night": summary.get("lastNight", 0),
            "status": summary.get("status", "UNKNOWN"),
            "baseline_low": summary.get("baselineLowUpper", 0),
            "baseline_high": summary.get("baselineBalancedUpper", 0),
        }

    # Body Battery
    bb_data = _safe_get(client.get_body_battery, date_str, default=[])
    if bb_data:
        values = [p.get("bodyBatteryLevel", 0) for p in bb_data if "bodyBatteryLevel" in p]
        if values:
            m["body_battery"] = {
                "max": max(values),
                "min": min(values),
                "current": values[-1] if values else 0,
            }

    # Stress
    stress_data = _safe_get(client.get_stress_data, date_str, default={})
    if stress_data:
        m["stress"] = {
            "avg": stress_data.get("overallStressLevel", 0),
            "max": stress_data.get("maxStressLevel", 0),
        }

    # Training Readiness
    try:
        tr_data = client.get_training_readiness(date_str)
        if tr_data:
            m["training_readiness"] = {
                "score": tr_data.get("score", 0),
                "level": tr_data.get("level", "UNKNOWN"),
            }
    except Exception:
        pass

    # Training Status
    try:
        ts_data = client.get_training_status(date_str)
        if ts_data:
            m["training_status"] = {
                "status": ts_data.get("trainingStatusType", "UNKNOWN"),
                "vo2_max_running": ts_data.get("vo2MaxPreciseValue", 0),
                "recovery_hours": ts_data.get("recoveryTimeInMinutes", 0) / 60,
            }
    except Exception:
        pass

    return data


def _format_summary(data: dict, date_str: str) -> str:
    """Format Garmin data for Telegram."""
    m = data.get("metrics", {})
    lines = [f"Garmin {date_str}:"]

    if "sleep" in m:
        s = m["sleep"]
        dur = s["duration_hours"]
        icon = "😴" if dur >= 7 else "😪" if dur >= 5 else "💀"
        lines.append(f"{icon} Сон: {dur}г (глибокий {s['deep_hours']}г, REM {s['rem_hours']}г)")
        if s.get("score"):
            lines.append(f"   Оцінка: {s['score']}/100")

    if "heart_rate" in m:
        hr = m["heart_rate"]
        lines.append(f"❤️ Пульс: спокій {hr['resting']}, мін {hr['min']}, макс {hr['max']}")

    if "hrv" in m:
        h = m["hrv"]
        lines.append(f"📈 HRV: {h['last_night']} (тижневий {h['weekly_avg']}, {h['status']})")

    if "body_battery" in m:
        bb = m["body_battery"]
        icon = "🟢" if bb["current"] >= 70 else "🟡" if bb["current"] >= 40 else "🔴"
        lines.append(f"🔋 Батарейка: {icon} {bb['current']}% (мін {bb['min']}, макс {bb['max']})")

    if "stress" in m:
        st = m["stress"]
        lines.append(f"😰 Стрес: середній {st['avg']}, макс {st['max']}")

    if "training_readiness" in m:
        tr = m["training_readiness"]
        score = tr["score"]
        icon = "🟢" if score >= 70 else "🟡" if score >= 50 else "🔴"
        lines.append(f"🎯 Готовність: {icon} {score}/100 ({tr['level']})")

    if "training_status" in m:
        ts = m["training_status"]
        rec = ts.get("recovery_hours", 0)
        rec_icon = "✅" if rec <= 24 else "⚠️" if rec <= 48 else "🛑"
        lines.append(f"📊 Статус: {ts['status']}, відновлення {rec_icon} {rec:.0f}г")

    if len(lines) == 1:
        return f"Немає даних Garmin за {date_str}."

    return "\n".join(lines)


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="get_garmin_daily",
            description=(
                "Get daily Garmin health metrics: sleep, HR, HRV, body battery, "
                "stress, training readiness, training status. "
                "Use when user asks about sleep, recovery, readiness to train, "
                "or health data from their watch."
            ),
            category="integration",
            handler=get_garmin_daily,
            input_schema={
                "type": "object",
                "properties": {
                    "date_str": {
                        "type": "string",
                        "description": "Date YYYY-MM-DD (empty = today)",
                    },
                },
            },
            tags=["health", "garmin", "sleep", "training"],
        )
    )
