"""Message Gateway — routing між каналами."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from posipaka.channels.base import BaseChannel
from posipaka.core.hooks.manager import HookEvent

if TYPE_CHECKING:
    from posipaka.config.settings import Settings
    from posipaka.core.agent import Agent


class MessageGateway:
    """Реєстрація каналів та unified message routing."""

    def __init__(self, agent: Agent, settings: Settings) -> None:
        self.agent = agent
        self.settings = settings
        self._channels: dict[str, BaseChannel] = {}
        self._running = False

    def _register_channels(self) -> None:
        """Зареєструвати активні канали."""
        enabled = self.settings.enabled_channels

        channel_map = {
            "telegram": ("posipaka.channels.telegram.bot", "TelegramChannel"),
            "discord": ("posipaka.channels.discord.bot", "DiscordChannel"),
            "slack": ("posipaka.channels.slack.bot", "SlackChannel"),
            "whatsapp": ("posipaka.channels.whatsapp.bot", "WhatsAppChannel"),
            "signal": ("posipaka.channels.signal.bot", "SignalChannel"),
        }

        for name, (module_path, class_name) in channel_map.items():
            if name in enabled:
                try:
                    import importlib

                    module = importlib.import_module(module_path)
                    channel_cls = getattr(module, class_name)
                    self._channels[name] = channel_cls(self.agent, self.settings)
                except ImportError as e:
                    logger.warning(f"{name} dependencies not installed: {e}")
                except Exception as e:
                    logger.error(f"Error registering {name}: {e}")

        if "cli" in enabled:
            from posipaka.channels.cli.repl import CLIChannel

            self._channels["cli"] = CLIChannel(self.agent, self.settings)

    async def start(self) -> None:
        """Запустити всі активні канали."""
        self._running = True
        self._register_channels()

        logger.info(f"Gateway starting channels: {list(self._channels.keys())}")
        await self.agent.hooks.emit(HookEvent.GATEWAY_START)

        # Start all channels concurrently
        tasks = []
        for name, channel in self._channels.items():
            logger.info(f"Starting channel: {name}")
            await self.agent.hooks.emit(HookEvent.CHANNEL_CONNECTED, {"channel": name})
            tasks.append(asyncio.create_task(channel.start()))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Зупинити всі канали."""
        self._running = False
        for name, channel in self._channels.items():
            try:
                await channel.stop()
                logger.info(f"Channel stopped: {name}")
                await self.agent.hooks.emit(HookEvent.CHANNEL_DISCONNECTED, {"channel": name})
            except Exception as e:
                logger.error(f"Error stopping {name}: {e}")
        await self.agent.hooks.emit(HookEvent.GATEWAY_STOP)
        logger.info("Gateway stopped")

    async def send_to_channel(self, channel_name: str, user_id: str, text: str) -> None:
        """Надіслати повідомлення через конкретний канал."""
        channel = self._channels.get(channel_name)
        if channel:
            await channel.send_message(user_id, text)
        else:
            logger.warning(f"Channel '{channel_name}' not registered")

    async def broadcast(self, user_id: str, text: str) -> None:
        """Надіслати повідомлення через всі канали."""
        for channel in self._channels.values():
            try:
                await channel.send_message(user_id, text)
            except Exception as e:
                logger.error(f"Broadcast error on {channel.name}: {e}")
