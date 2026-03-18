"""Posipaka — Weather Integration (OpenWeatherMap API)."""

from __future__ import annotations

import os
from typing import Any

import httpx

OWM_BASE = "https://api.openweathermap.org/data/2.5"


def _get_api_key() -> str:
    return os.environ.get("OPENWEATHERMAP_API_KEY", "")


async def get_weather(city: str, units: str = "metric") -> str:
    """Отримати поточну погоду."""
    api_key = _get_api_key()
    if not api_key:
        return "OpenWeatherMap API ключ не налаштовано. Встановіть OPENWEATHERMAP_API_KEY."

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{OWM_BASE}/weather",
                params={"q": city, "appid": api_key, "units": units, "lang": "uk"},
            )
            response.raise_for_status()

        data = response.json()
        temp = data["main"]["temp"]
        feels = data["main"]["feels_like"]
        desc = data["weather"][0]["description"]
        humidity = data["main"]["humidity"]
        wind = data["wind"]["speed"]
        unit_sym = "°C" if units == "metric" else "°F"

        return (
            f"Погода в {city}:\n"
            f"🌡️ {temp}{unit_sym} (відчувається як {feels}{unit_sym})\n"
            f"☁️ {desc}\n"
            f"💧 Вологість: {humidity}%\n"
            f"💨 Вітер: {wind} м/с"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Місто '{city}' не знайдено"
        return f"Помилка API: {e.response.status_code}"
    except Exception as e:
        return f"Помилка погоди: {e}"


async def get_forecast(city: str, days: int = 3, units: str = "metric") -> str:
    """Отримати прогноз погоди."""
    api_key = _get_api_key()
    if not api_key:
        return "OpenWeatherMap API ключ не налаштовано."

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{OWM_BASE}/forecast",
                params={"q": city, "appid": api_key, "units": units, "lang": "uk", "cnt": days * 8},
            )
            response.raise_for_status()

        data = response.json()
        unit_sym = "°C" if units == "metric" else "°F"

        lines = [f"Прогноз для {city} на {days} дні:\n"]
        seen_dates = set()
        for item in data.get("list", []):
            date = item["dt_txt"][:10]
            if date in seen_dates:
                continue
            seen_dates.add(date)
            if len(seen_dates) > days:
                break

            temp = item["main"]["temp"]
            desc = item["weather"][0]["description"]
            lines.append(f"📅 {date}: {temp}{unit_sym}, {desc}")

        return "\n".join(lines)
    except Exception as e:
        return f"Помилка прогнозу: {e}"


def register(registry: Any) -> None:
    """Реєстрація weather tools."""
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="get_weather",
            description="Get current weather for a city. Requires OPENWEATHERMAP_API_KEY.",
            category="integration",
            handler=get_weather,
            input_schema={
                "type": "object",
                "required": ["city"],
                "properties": {
                    "city": {"type": "string", "description": "City name (e.g. 'Kyiv', 'London')"},
                    "units": {
                        "type": "string",
                        "description": "Units: metric (°C) or imperial (°F)",
                    },
                },
            },
            tags=["weather"],
        )
    )

    registry.register(
        ToolDefinition(
            name="get_forecast",
            description="Get weather forecast for a city for next N days.",
            category="integration",
            handler=get_forecast,
            input_schema={
                "type": "object",
                "required": ["city"],
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                    "days": {"type": "integer", "description": "Number of days (default 3)"},
                    "units": {"type": "string", "description": "Units: metric or imperial"},
                },
            },
            tags=["weather"],
        )
    )
