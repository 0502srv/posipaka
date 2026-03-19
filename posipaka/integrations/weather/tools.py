"""Posipaka — Weather Integration (Open-Meteo API, no key required)."""

from __future__ import annotations

from typing import Any

import httpx

_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# WMO Weather interpretation codes → Ukrainian descriptions
_WMO_CODES: dict[int, str] = {
    0: "ясно",
    1: "переважно ясно",
    2: "мінлива хмарність",
    3: "хмарно",
    45: "туман",
    48: "паморозний туман",
    51: "легка мряка",
    53: "мряка",
    55: "сильна мряка",
    56: "крижана мряка",
    57: "сильна крижана мряка",
    61: "невеликий дощ",
    63: "дощ",
    65: "сильний дощ",
    66: "крижаний дощ",
    67: "сильний крижаний дощ",
    71: "невеликий сніг",
    73: "сніг",
    75: "сильний сніг",
    77: "снігова крупа",
    80: "невеликі зливи",
    81: "зливи",
    82: "сильні зливи",
    85: "невеликий снігопад",
    86: "сильний снігопад",
    95: "гроза",
    96: "гроза з градом",
    99: "сильна гроза з градом",
}


async def _geocode(city: str) -> tuple[float, float, str] | None:
    """Знайти координати міста. Повертає (lat, lon, display_name) або None."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _GEOCODING_URL,
                params={"name": city, "count": 1, "language": "uk", "format": "json"},
            )
            resp.raise_for_status()
        data = resp.json()
        results = data.get("results")
        if not results:
            return None
        r = results[0]
        name = r.get("name", city)
        country = r.get("country", "")
        display = f"{name}, {country}" if country else name
        return r["latitude"], r["longitude"], display
    except Exception:
        return None


async def get_weather(city: str) -> str:
    """Отримати поточну погоду для міста."""
    geo = await _geocode(city)
    if not geo:
        return f"Місто '{city}' не знайдено."

    lat, lon, display_name = geo
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _WEATHER_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                    "timezone": "auto",
                },
            )
            resp.raise_for_status()

        current = resp.json()["current"]
        temp = current["temperature_2m"]
        feels = current["apparent_temperature"]
        humidity = current["relative_humidity_2m"]
        wind = current["wind_speed_10m"]
        code = current["weather_code"]
        desc = _WMO_CODES.get(code, f"код {code}")

        return (
            f"Погода в {display_name}:\n"
            f"🌡️ {temp}°C (відчувається як {feels}°C)\n"
            f"☁️ {desc}\n"
            f"💧 Вологість: {humidity}%\n"
            f"💨 Вітер: {wind} км/год"
        )
    except Exception as e:
        return f"Помилка отримання погоди: {e}"


async def get_forecast(city: str, days: int = 3) -> str:
    """Отримати прогноз погоди на кілька днів."""
    geo = await _geocode(city)
    if not geo:
        return f"Місто '{city}' не знайдено."

    lat, lon, display_name = geo
    days = max(1, min(days, 16))

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _WEATHER_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max,wind_speed_10m_max",
                    "timezone": "auto",
                    "forecast_days": days,
                },
            )
            resp.raise_for_status()

        daily = resp.json()["daily"]
        lines = [f"Прогноз для {display_name} на {days} дн.:\n"]

        for i in range(len(daily["time"])):
            date = daily["time"][i]
            t_max = daily["temperature_2m_max"][i]
            t_min = daily["temperature_2m_min"][i]
            code = daily["weather_code"][i]
            precip = daily["precipitation_probability_max"][i]
            wind = daily["wind_speed_10m_max"][i]
            desc = _WMO_CODES.get(code, f"код {code}")

            lines.append(
                f"📅 {date}: {t_min}..{t_max}°C, {desc}, "
                f"опади {precip}%, вітер {wind} км/год"
            )

        return "\n".join(lines)
    except Exception as e:
        return f"Помилка прогнозу: {e}"


def register(registry: Any) -> None:
    """Реєстрація weather tools."""
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="get_weather",
            description="Get current weather for a city. Use when user asks about weather, temperature, rain, snow, wind, погода, температура.",
            category="integration",
            handler=get_weather,
            input_schema={
                "type": "object",
                "required": ["city"],
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name (e.g. 'Kyiv', 'London', 'Дніпро')",
                    },
                },
            },
            tags=["weather"],
        )
    )

    registry.register(
        ToolDefinition(
            name="get_forecast",
            description="Get weather forecast for a city for next N days (up to 16). Use when user asks about forecast, прогноз, погода на завтра/тиждень.",
            category="integration",
            handler=get_forecast,
            input_schema={
                "type": "object",
                "required": ["city"],
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name (e.g. 'Kyiv', 'London', 'Дніпро')",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of forecast days (1-16, default 3)",
                    },
                },
            },
            tags=["weather"],
        )
    )
