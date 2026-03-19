"""Posipaka — Slack Integration Tools (not the channel — agent tools for Slack)."""

from __future__ import annotations

import os
from typing import Any


def _get_slack_client():
    try:
        from slack_sdk import WebClient

        token = os.environ.get("SLACK_BOT_TOKEN", "")
        if not token:
            return None
        return WebClient(token=token)
    except ImportError:
        return None


async def slack_send_message(channel: str, text: str) -> str:
    """Надіслати повідомлення в Slack канал (requires approval)."""
    client = _get_slack_client()
    if not client:
        return "Slack не налаштовано (SLACK_BOT_TOKEN)."
    try:
        import asyncio

        await asyncio.to_thread(client.chat_postMessage, channel=channel, text=text)
        return f"Повідомлення надіслано в #{channel}"
    except Exception as e:
        return f"Slack помилка: {e}"


async def slack_list_channels() -> str:
    client = _get_slack_client()
    if not client:
        return "Slack не налаштовано."
    try:
        import asyncio

        result = await asyncio.to_thread(
            client.conversations_list, types="public_channel", limit=50
        )
        channels = result.get("channels", [])
        if not channels:
            return "Каналів не знайдено."
        lines = ["Slack канали:\n"]
        for ch in channels:
            lines.append(f"• #{ch['name']} ({ch.get('num_members', '?')} учасників)")
        return "\n".join(lines)
    except Exception as e:
        return f"Помилка: {e}"


async def slack_search_messages(query: str) -> str:
    client = _get_slack_client()
    if not client:
        return "Slack не налаштовано."
    try:
        import asyncio

        from posipaka.security.injection import sanitize_external_content

        result = await asyncio.to_thread(client.search_messages, query=query, count=10)
        messages = result.get("messages", {}).get("matches", [])
        if not messages:
            return f"Нічого не знайдено: {query}"
        lines = [f"Slack пошук: '{query}'\n"]
        for m in messages:
            user = m.get("username", "?")
            text = m.get("text", "")[:100]
            channel = m.get("channel", {}).get("name", "?")
            lines.append(f"• [{user} в #{channel}] {text}")
        return sanitize_external_content("\n".join(lines), source="slack")
    except Exception as e:
        return f"Помилка: {e}"


def register(registry: Any) -> None:
    import os

    if not os.environ.get("SLACK_BOT_TOKEN"):
        return

    from posipaka.core.tools.registry import ToolDefinition

    registry.register(
        ToolDefinition(
            name="slack_send_message",
            description="Send a message to a Slack channel. Requires approval.",
            category="integration",
            handler=slack_send_message,
            input_schema={
                "type": "object",
                "required": ["channel", "text"],
                "properties": {"channel": {"type": "string"}, "text": {"type": "string"}},
            },
            requires_approval=True,
            tags=["slack"],
        )
    )
    registry.register(
        ToolDefinition(
            name="slack_list_channels",
            description="List Slack channels.",
            category="integration",
            handler=slack_list_channels,
            input_schema={"type": "object", "properties": {}},
            tags=["slack"],
        )
    )
    registry.register(
        ToolDefinition(
            name="slack_search_messages",
            description="Search messages in Slack workspace.",
            category="integration",
            handler=slack_search_messages,
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
            tags=["slack"],
        )
    )
