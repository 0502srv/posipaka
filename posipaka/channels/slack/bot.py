"""Posipaka — Slack Channel (Slack Bolt + Socket Mode)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from posipaka.channels.base import BaseChannel
from posipaka.utils.formatting import split_message

if TYPE_CHECKING:
    from posipaka.config.settings import Settings
    from posipaka.core.agent import Agent


class SlackChannel(BaseChannel):
    """Slack канал через Slack Bolt + Socket Mode."""

    def __init__(self, agent: Agent, settings: Settings) -> None:
        super().__init__(agent)
        self.settings = settings

    @property
    def name(self) -> str:
        return "slack"

    async def start(self) -> None:
        try:
            from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
            from slack_bolt.async_app import AsyncApp
        except ImportError:
            logger.error("slack-bolt not installed. Run: pip install posipaka[slack]")
            return

        bot_token = self.settings.slack.bot_token.get_secret_value()
        app_token = self.settings.slack.app_token.get_secret_value()

        if not bot_token or not app_token:
            logger.error("SLACK_BOT_TOKEN and SLACK_APP_TOKEN required")
            return

        app = AsyncApp(token=bot_token)

        @app.event("app_mention")
        async def handle_mention(event, say):
            text = event.get("text", "")
            user_id = event.get("user", "")
            # Remove bot mention
            import re

            text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()

            session = self.agent.sessions.get_or_create(user_id, "slack")
            response_parts = []
            async for chunk in self.agent.handle_message(text, session.id):
                response_parts.append(chunk)

            full_response = "\n".join(response_parts)
            for part in split_message(full_response, 3000):
                await say(part, thread_ts=event.get("ts"))

        @app.event("message")
        async def handle_dm(event, say):
            if event.get("channel_type") != "im":
                return
            text = event.get("text", "")
            user_id = event.get("user", "")

            session = self.agent.sessions.get_or_create(user_id, "slack")
            response_parts = []
            async for chunk in self.agent.handle_message(text, session.id):
                response_parts.append(chunk)

            await say("\n".join(response_parts))

        handler = AsyncSocketModeHandler(app, app_token)
        logger.info("Slack bot starting (Socket Mode)...")
        await handler.start_async()

    async def stop(self) -> None:
        pass

    async def send_message(self, user_id: str, text: str) -> None:
        logger.warning("Slack direct send not implemented in Socket Mode")
