"""Voice Pipeline — STT + TTS (секція 38 MASTER.md)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from loguru import logger


class STTProvider:
    """Speech-to-Text провайдер."""

    def __init__(self, provider: str = "whisper_local") -> None:
        self.provider = provider

    async def transcribe(self, audio_path: Path) -> str:
        """Транскрибувати аудіо в текст."""
        if self.provider == "whisper_local":
            return await self._whisper_local(audio_path)
        elif self.provider == "openai_whisper":
            return await self._openai_whisper(audio_path)
        return "STT провайдер не налаштовано"

    async def _whisper_local(self, audio_path: Path) -> str:
        """Локальний Whisper (openai-whisper pip package)."""
        try:
            import whisper

            model = await asyncio.to_thread(whisper.load_model, "base")
            result = await asyncio.to_thread(model.transcribe, str(audio_path), language=None)
            return result.get("text", "")
        except ImportError:
            return "openai-whisper не встановлено: pip install openai-whisper"
        except Exception as e:
            logger.error(f"Whisper error: {e}")
            return f"STT помилка: {e}"

    async def _openai_whisper(self, audio_path: Path) -> str:
        """OpenAI Whisper API."""
        try:
            import openai

            client = openai.AsyncOpenAI()
            with open(audio_path, "rb") as f:
                result = await client.audio.transcriptions.create(model="whisper-1", file=f)
            return result.text
        except Exception as e:
            return f"OpenAI Whisper error: {e}"


class TTSProvider:
    """Text-to-Speech провайдер."""

    def __init__(
        self,
        provider: str = "disabled",
        voice: str = "uk-UA-OstapNeural",
    ) -> None:
        self.provider = provider
        self.voice = voice

    async def synthesize(self, text: str) -> Path | None:
        """Синтезувати мовлення. Повертає шлях до аудіо файлу."""
        if self.provider == "disabled":
            return None
        if self.provider == "edge_tts":
            return await self._edge_tts(text)
        return None

    async def _edge_tts(self, text: str) -> Path | None:
        """Microsoft Edge TTS — безкоштовний, якісний."""
        try:
            import edge_tts

            output_path = Path(tempfile.mktemp(suffix=".mp3"))
            communicate = edge_tts.Communicate(text, self.voice)
            await communicate.save(str(output_path))
            return output_path
        except ImportError:
            logger.warning("edge-tts не встановлено: pip install edge-tts")
            return None
        except Exception as e:
            logger.error(f"Edge TTS error: {e}")
            return None


class VoicePipeline:
    """Повний voice pipeline: STT → Agent → TTS."""

    def __init__(
        self,
        stt_provider: str = "whisper_local",
        tts_provider: str = "disabled",
        tts_voice: str = "uk-UA-OstapNeural",
        reply_mode: str = "text_only",
    ) -> None:
        self.stt = STTProvider(stt_provider)
        self.tts = TTSProvider(tts_provider, tts_voice)
        self.reply_mode = reply_mode  # text_only | voice_only | both | auto

    async def process_voice(self, audio_path: Path) -> str:
        """STT: конвертувати голосове повідомлення в текст."""
        return await self.stt.transcribe(audio_path)

    async def generate_voice_reply(self, text: str) -> Path | None:
        """TTS: згенерувати голосову відповідь."""
        if self.reply_mode == "text_only":
            return None
        return await self.tts.synthesize(text)

    @property
    def stt_available(self) -> bool:
        return self.stt.provider != "disabled"

    @property
    def tts_available(self) -> bool:
        return self.tts.provider != "disabled"
