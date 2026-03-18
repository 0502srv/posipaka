"""Posipaka — Discord Channel (discord.py)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from posipaka.channels.base import BaseChannel
from posipaka.utils.formatting import split_message

if TYPE_CHECKING:
    from posipaka.config.settings import Settings
    from posipaka.core.agent import Agent


class DiscordChannel(BaseChannel):
    """Discord канал через discord.py."""

    def __init__(self, agent: Agent, settings: Settings) -> None:
        super().__init__(agent)
        self.settings = settings
        self._client = None

    @property
    def name(self) -> str:
        return "discord"

    async def start(self) -> None:
        try:
            import discord
            from discord.ext import commands
        except ImportError:
            logger.error("discord.py not installed. Run: pip install posipaka[discord]")
            return

        token = self.settings.discord.token.get_secret_value()
        if not token:
            logger.error("DISCORD_TOKEN not set")
            return

        intents = discord.Intents.default()
        intents.message_content = True
        bot = commands.Bot(command_prefix="!", intents=intents)
        self._client = bot

        @bot.event
        async def on_ready():
            logger.info(f"Discord bot ready: {bot.user}")

        @bot.event
        async def on_message(message):
            if message.author == bot.user:
                return

            # Check if mentioned or in DM
            if bot.user not in message.mentions and not isinstance(
                message.channel, discord.DMChannel
            ):
                return

            content = message.content.replace(f"<@{bot.user.id}>", "").strip()
            session = self.agent.sessions.get_or_create(str(message.author.id), "discord")

            async with message.channel.typing():
                response_parts = []
                async for chunk in self.agent.handle_message(content, session.id):
                    response_parts.append(chunk)

            full_response = "\n".join(response_parts)
            for part in split_message(full_response, 2000):
                await message.reply(part)

        await bot.start(token)

    async def stop(self) -> None:
        if self._client:
            await self._client.close()

    async def send_message(self, user_id: str, text: str) -> None:
        if not self._client:
            return
        try:
            user = await self._client.fetch_user(int(user_id))
            for chunk in split_message(text, 2000):
                await user.send(chunk)
        except Exception as e:
            logger.error(f"Discord send error: {e}")
