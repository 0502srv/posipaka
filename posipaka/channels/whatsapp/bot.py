"""Posipaka — WhatsApp Channel (Twilio API).

D.1: Voice message support via Twilio media URL download + STT.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from loguru import logger

from posipaka.channels.base import BaseChannel

if TYPE_CHECKING:
    from posipaka.config.settings import Settings
    from posipaka.core.agent import Agent


class WhatsAppChannel(BaseChannel):
    """WhatsApp канал через Twilio API."""

    def __init__(self, agent: Agent, settings: Settings) -> None:
        super().__init__(agent)
        self.settings = settings

    @property
    def name(self) -> str:
        return "whatsapp"

    async def start(self) -> None:
        logger.info(
            "WhatsApp channel requires webhook setup via FastAPI endpoint /webhooks/whatsapp"
        )

    async def stop(self) -> None:
        pass

    async def send_message(self, user_id: str, text: str) -> None:
        try:
            from twilio.rest import Client

            sid = self.settings.whatsapp.account_sid.get_secret_value()
            token = self.settings.whatsapp.auth_token.get_secret_value()
            from_number = self.settings.whatsapp.from_number

            client = Client(sid, token)
            client.messages.create(
                body=text,
                from_=f"whatsapp:{from_number}",
                to=f"whatsapp:{user_id}",
            )
        except ImportError:
            logger.error("twilio not installed. Run: pip install posipaka[whatsapp]")
        except Exception as e:
            logger.error(f"WhatsApp send error: {e}")

    async def handle_incoming_webhook(self, form_data: dict) -> str:
        """Handle incoming WhatsApp webhook from Twilio.

        D.1: Supports voice messages via MediaUrl download + STT.
        """
        from_number = form_data.get("From", "").replace("whatsapp:", "")
        body = form_data.get("Body", "")
        num_media = int(form_data.get("NumMedia", "0"))

        # D.1: Voice / audio message
        if num_media > 0:
            media_type = form_data.get("MediaContentType0", "")
            media_url = form_data.get("MediaUrl0", "")

            if media_type.startswith("audio/") and media_url:
                body = await self._transcribe_voice(media_url, media_type)
                if not body:
                    return "Не вдалося розпізнати голосове повідомлення."

        if not body:
            return ""

        session = self.agent.sessions.get_or_create(from_number, "whatsapp")

        response_parts = []
        async for chunk in self.agent.handle_message(body, session.id):
            response_parts.append(chunk)

        return "\n".join(response_parts)

    async def _transcribe_voice(self, media_url: str, content_type: str) -> str:
        """D.1: Download and transcribe voice message."""
        try:
            from posipaka.core.voice import VoiceProcessor

            # Determine file extension from content type
            ext = ".ogg"
            if "mp4" in content_type or "mp4a" in content_type:
                ext = ".mp4"
            elif "amr" in content_type:
                ext = ".amr"
            elif "wav" in content_type:
                ext = ".wav"

            # Download via Twilio (requires basic auth)
            sid = self.settings.whatsapp.account_sid.get_secret_value()
            token = self.settings.whatsapp.auth_token.get_secret_value()

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(media_url, auth=(sid, token))
                resp.raise_for_status()

            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = Path(tmp.name)

            processor = VoiceProcessor()
            text = await processor.transcribe(tmp_path)
            tmp_path.unlink(missing_ok=True)
            return text or ""

        except ImportError:
            logger.warning("Voice processing not available (pip install posipaka[voice])")
            return ""
        except Exception as e:
            logger.error(f"WhatsApp voice transcription error: {e}")
            return ""
