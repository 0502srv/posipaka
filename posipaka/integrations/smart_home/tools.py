"""Smart Home integration — Home Assistant.

Connects to Home Assistant REST API.
Requires: HASS_URL and HASS_TOKEN env vars.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


def _hass_headers() -> dict[str, str]:
    token = os.environ.get("HASS_TOKEN", "")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _hass_url() -> str:
    return os.environ.get("HASS_URL", "http://homeassistant.local:8123")


async def hass_states() -> str:
    """Отримати стани всіх пристроїв Home Assistant."""
    url = _hass_url()
    token = os.environ.get("HASS_TOKEN", "")
    if not token:
        return "Home Assistant не налаштовано. Встановіть HASS_URL та HASS_TOKEN."

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{url}/api/states", headers=_hass_headers())
            resp.raise_for_status()
            states = resp.json()

        lines = [f"Home Assistant — {len(states)} пристроїв:"]
        for s in states[:30]:
            entity_id = s.get("entity_id", "")
            state = s.get("state", "")
            name = s.get("attributes", {}).get("friendly_name", entity_id)
            lines.append(f"  {name}: {state}")
        if len(states) > 30:
            lines.append(f"  ... та ще {len(states) - 30}")
        return "\n".join(lines)
    except httpx.HTTPError as e:
        return f"Помилка Home Assistant API: {e}"


async def hass_turn_on(entity_id: str) -> str:
    """Увімкнути пристрій Home Assistant."""
    url = _hass_url()
    token = os.environ.get("HASS_TOKEN", "")
    if not token:
        return "Home Assistant не налаштовано."

    try:
        domain = entity_id.split(".")[0] if "." in entity_id else "homeassistant"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{url}/api/services/{domain}/turn_on",
                headers=_hass_headers(),
                json={"entity_id": entity_id},
            )
            resp.raise_for_status()
        return f"Увімкнено: {entity_id}"
    except httpx.HTTPError as e:
        return f"Помилка: {e}"


async def hass_turn_off(entity_id: str) -> str:
    """Вимкнути пристрій Home Assistant."""
    url = _hass_url()
    token = os.environ.get("HASS_TOKEN", "")
    if not token:
        return "Home Assistant не налаштовано."

    try:
        domain = entity_id.split(".")[0] if "." in entity_id else "homeassistant"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{url}/api/services/{domain}/turn_off",
                headers=_hass_headers(),
                json={"entity_id": entity_id},
            )
            resp.raise_for_status()
        return f"Вимкнено: {entity_id}"
    except httpx.HTTPError as e:
        return f"Помилка: {e}"


async def hass_call_service(domain: str, service: str, entity_id: str = "", data: str = "") -> str:
    """Викликати довільний сервіс Home Assistant."""
    url = _hass_url()
    token = os.environ.get("HASS_TOKEN", "")
    if not token:
        return "Home Assistant не налаштовано."

    import json as _json

    payload: dict = {}
    if entity_id:
        payload["entity_id"] = entity_id
    if data:
        try:
            payload.update(_json.loads(data))
        except _json.JSONDecodeError:
            return "Невалідний JSON у параметрі data."

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{url}/api/services/{domain}/{service}",
                headers=_hass_headers(),
                json=payload,
            )
            resp.raise_for_status()
        return f"Сервіс {domain}.{service} виконано."
    except httpx.HTTPError as e:
        return f"Помилка: {e}"


def register(registry: Any) -> None:
    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="hass_states",
            description="Get all device states from Home Assistant smart home.",
            category="smart_home",
            handler=hass_states,
            input_schema={"type": "object", "properties": {}},
            tags=["smart_home", "homeassistant"],
        )
    )

    registry.register(
        ToolDefinition(
            name="hass_turn_on",
            description="Turn on a Home Assistant device (light, switch, etc).",
            category="smart_home",
            handler=hass_turn_on,
            requires_approval=True,
            input_schema={
                "type": "object",
                "required": ["entity_id"],
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Entity ID, e.g. light.living_room",
                    },
                },
            },
            tags=["smart_home"],
        )
    )

    registry.register(
        ToolDefinition(
            name="hass_turn_off",
            description="Turn off a Home Assistant device.",
            category="smart_home",
            handler=hass_turn_off,
            requires_approval=True,
            input_schema={
                "type": "object",
                "required": ["entity_id"],
                "properties": {
                    "entity_id": {"type": "string", "description": "Entity ID"},
                },
            },
            tags=["smart_home"],
        )
    )

    registry.register(
        ToolDefinition(
            name="hass_call_service",
            description="Call any Home Assistant service (advanced).",
            category="smart_home",
            handler=hass_call_service,
            requires_approval=True,
            input_schema={
                "type": "object",
                "required": ["domain", "service"],
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Service domain (e.g. light, climate)",
                    },
                    "service": {
                        "type": "string",
                        "description": "Service name (e.g. turn_on, set_temperature)",
                    },
                    "entity_id": {"type": "string", "description": "Target entity ID"},
                    "data": {"type": "string", "description": "Additional data as JSON string"},
                },
            },
            tags=["smart_home"],
        )
    )
