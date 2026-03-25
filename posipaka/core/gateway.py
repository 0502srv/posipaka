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

        # Store gateway reference on agent so cron delivery works
        self.agent.gateway = self

        logger.info(f"Gateway starting channels: {list(self._channels.keys())}")
        await self.agent.hooks.emit(HookEvent.GATEWAY_START)

        # Auto-register cron jobs in scheduler and start it
        self._start_cron_scheduler()

        # Start all channels
        for name, channel in self._channels.items():
            logger.info(f"Starting channel: {name}")
            await self.agent.hooks.emit(HookEvent.CHANNEL_CONNECTED, {"channel": name})
            await channel.start()

        # Keep gateway alive while channels run
        try:
            while self._running:
                await asyncio.sleep(1)
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Зупинити всі канали та дочекатися cron jobs."""
        self._running = False

        # Stop scheduler first, then wait for running cron jobs
        scheduler = getattr(self.agent, "scheduler", None)
        if scheduler and scheduler.running:
            scheduler.stop(wait=False)

        cron_executor = getattr(self.agent, "cron_executor", None)
        if cron_executor:
            await cron_executor.graceful_shutdown(timeout=30.0)

        for name, channel in self._channels.items():
            try:
                await channel.stop()
                logger.info(f"Channel stopped: {name}")
                await self.agent.hooks.emit(HookEvent.CHANNEL_DISCONNECTED, {"channel": name})
            except Exception as e:
                logger.error(f"Error stopping {name}: {e}")

        # Close cron history DB
        if hasattr(self.agent, "cron_history") and self.agent.cron_history:
            self.agent.cron_history.close()

        await self.agent.hooks.emit(HookEvent.GATEWAY_STOP)
        logger.info("Gateway stopped")

    def _start_cron_scheduler(self) -> None:
        """Register CronEngine jobs in APScheduler and start it."""
        scheduler = getattr(self.agent, "scheduler", None)
        cron_engine = getattr(self.agent, "cron_engine", None)
        cron_executor = getattr(self.agent, "cron_executor", None)
        if not (scheduler and cron_engine and cron_executor):
            return
        # Register jobs (non-fatal if fails)
        try:

            def agent_fn_provider():
                return getattr(self.agent, "_cron_agent_fn", None)

            scheduler.register_cron_jobs(
                cron_engine,
                cron_executor,
                agent_fn_provider,
            )
        except Exception as e:
            logger.warning(f"Cron job registration error (non-fatal): {e}")

        # Daily cleanup of old execution history (03:00)
        try:
            cron_history = getattr(self.agent, "cron_history", None)
            if cron_history:

                async def _daily_cleanup() -> None:
                    cron_history.cleanup(days=30)

                scheduler.add_cron(
                    "system:cron_history_cleanup",
                    _daily_cleanup,
                    hour=3,
                    minute=0,
                )
        except Exception as e:
            logger.warning(f"Cron cleanup registration error: {e}")

        # ALWAYS start scheduler — even if registration partially failed
        try:
            scheduler.start()
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")

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
