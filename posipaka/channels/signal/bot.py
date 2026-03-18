"""Posipaka — Signal Channel (signal-cli REST API)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx
from loguru import logger

from posipaka.channels.base import BaseChannel

if TYPE_CHECKING:
    from posipaka.config.settings import Settings
    from posipaka.core.agent import Agent


class SignalChannel(BaseChannel):
    """Signal канал через signal-cli REST API."""

    def __init__(self, agent: Agent, settings: Settings) -> None:
        super().__init__(agent)
        self.settings = settings
        self._running = False

    @property
    def name(self) -> str:
        return "signal"

    async def start(self) -> None:
        base_url = self.settings.signal.signal_cli_url
        phone = self.settings.signal.phone_number

        if not phone:
            logger.error("SIGNAL_PHONE_NUMBER not set")
            return

        self._running = True
        logger.info(f"Signal polling started: {base_url}")

        async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
            while self._running:
                try:
                    resp = await client.get(f"/v1/receive/{phone}")
                    if resp.status_code == 200:
                        messages = resp.json()
                        for msg in messages:
                            envelope = msg.get("envelope", {})
                            data_msg = envelope.get("dataMessage", {})
                            text = data_msg.get("message", "")
                            sender = envelope.get("source", "")

                            if text and sender:
                                session = self.agent.sessions.get_or_create(sender, "signal")
                                response_parts = []
                                async for chunk in self.agent.handle_message(text, session.id):
                                    response_parts.append(chunk)
                                await self.send_message(sender, "\n".join(response_parts))
                except Exception as e:
                    logger.debug(f"Signal poll error: {e}")

                await asyncio.sleep(2)

    async def stop(self) -> None:
        self._running = False

    async def send_message(self, user_id: str, text: str) -> None:
        base_url = self.settings.signal.signal_cli_url
        phone = self.settings.signal.phone_number

        try:
            async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
                await client.post(
                    "/v2/send",
                    json={
                        "message": text,
                        "number": phone,
                        "recipients": [user_id],
                    },
                )
        except Exception as e:
            logger.error(f"Signal send error: {e}")
