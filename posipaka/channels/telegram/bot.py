"""Posipaka — Telegram Channel (python-telegram-bot).

D.1: Voice message support (STT via VoiceProcessor)
D.2: File/document processing (PDF, DOCX, XLSX, images)
D.3: Conversation threading (reply context)
"""

from __future__ import annotations

import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from posipaka.channels.base import BaseChannel
from posipaka.utils.formatting import split_message
from posipaka.utils.i18n.translator import get_translator
from posipaka.utils.rate_limiter import RateLimiter

if TYPE_CHECKING:
    from posipaka.config.settings import Settings
    from posipaka.core.agent import Agent

# D.2: Max file size for downloads (20MB)
MAX_FILE_SIZE = 20 * 1024 * 1024

# D.3: Reply context cache size
_REPLY_CACHE_MAX = 500


class _LRUCache(OrderedDict):
    """Simple LRU cache for reply context (D.3)."""

    def __init__(self, maxsize: int = _REPLY_CACHE_MAX) -> None:
        super().__init__()
        self._maxsize = maxsize

    def get_val(self, key):
        if key in self:
            self.move_to_end(key)
            return self[key]
        return None

    def put(self, key, value):
        if key in self:
            self.move_to_end(key)
        self[key] = value
        if len(self) > self._maxsize:
            self.popitem(last=False)


class TelegramChannel(BaseChannel):
    """Telegram канал через python-telegram-bot."""

    def __init__(self, agent: Agent, settings: Settings) -> None:
        super().__init__(agent)
        self.settings = settings
        self._app = None
        self._rate_limiters: dict[int, RateLimiter] = {}
        self._reply_cache: _LRUCache = _LRUCache()  # D.3: msg_id -> response text
        self._setup_wizard = None  # Lazy-initialized messenger setup wizard
        self._t = get_translator(settings.soul.language)  # D.5: multi-language system messages

    @property
    def name(self) -> str:
        return "telegram"

    def _get_rate_limiter(self, user_id: int) -> RateLimiter:
        if user_id not in self._rate_limiters:
            self._rate_limiters[user_id] = RateLimiter(
                rate=self.settings.telegram.rate_limit_per_minute,
                per=60.0,
            )
        return self._rate_limiters[user_id]

    def _is_authorized(self, user_id: int) -> bool:
        """Перевірити авторизацію."""
        allowed = self.settings.telegram.allowed_user_ids
        if not allowed:
            return True  # No allowlist — open for everyone
        return user_id in allowed

    def _is_owner(self, user_id: int) -> bool:
        """Перевірити чи є користувач власником."""
        owner = self.settings.telegram.owner_id
        return owner != 0 and user_id == owner

    async def start(self) -> None:
        """Запустити Telegram бота."""
        try:
            from telegram.ext import (
                Application,
                CallbackQueryHandler,
                CommandHandler,
                MessageHandler,
                filters,
            )
        except ImportError:
            logger.error("python-telegram-bot not installed. Run: pip install posipaka[telegram]")
            return

        token = self.settings.telegram.token.get_secret_value()
        if not token:
            logger.error("TELEGRAM_TOKEN not set")
            return

        self._app = Application.builder().token(token).build()

        # Commands
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("reset", self._cmd_reset))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("memory", self._cmd_memory))
        self._app.add_handler(CommandHandler("skills", self._cmd_skills))
        self._app.add_handler(CommandHandler("cost", self._cmd_cost))
        self._app.add_handler(CommandHandler("persona", self._cmd_persona))
        self._app.add_handler(CommandHandler("cron", self._cmd_cron))
        self._app.add_handler(CommandHandler("heartbeat", self._cmd_heartbeat))
        self._app.add_handler(CommandHandler("setup", self._cmd_setup))

        # Callback queries (approval buttons)
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))

        # Regular messages
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

        # D.1: Voice messages
        self._app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self._handle_voice))
        self._app.add_handler(MessageHandler(filters.VIDEO_NOTE, self._handle_voice))

        # D.2: Documents and photos
        self._app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
        self._app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))

        logger.info("Telegram bot starting...")
        await self._app.initialize()

        # Скинути webhook перед polling щоб уникнути Conflict
        await self._app.bot.delete_webhook(drop_pending_updates=True)

        await self._app.start()

        if self.settings.telegram.use_webhook and self.settings.telegram.webhook_url:
            await self._app.updater.start_webhook(
                listen="0.0.0.0",
                port=8443,
                url_path="webhooks/telegram",
                webhook_url=f"{self.settings.telegram.webhook_url}/webhooks/telegram",
            )
            logger.info("Telegram webhook started")
        else:
            await self._app.updater.start_polling(
                poll_interval=1.0,
                timeout=10,
                read_timeout=15,
            )
            logger.info("Telegram polling started")

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram bot stopped")

    async def send_message(self, user_id: str, text: str) -> None:
        """Надіслати повідомлення."""
        if not self._app:
            return
        for chunk in split_message(text, 4096):
            try:
                await self._app.bot.send_message(
                    chat_id=int(user_id),
                    text=chunk,
                    parse_mode="Markdown",
                )
            except Exception:
                # Fallback to plain text if Markdown fails
                await self._app.bot.send_message(
                    chat_id=int(user_id),
                    text=chunk,
                )

    async def _cmd_start(self, update, context) -> None:
        user = update.effective_user
        user_id = user.id

        # Auto-set owner
        if self.settings.telegram.owner_id == 0:
            self.settings.telegram.owner_id = user_id
            logger.info(f"Auto-set Telegram owner: {user_id}")

        self.agent.sessions.get_or_create(str(user_id), "telegram")
        await update.message.reply_text(
            f"Привіт, {user.first_name}! Я Posipaka — ваш AI-асистент.\n\n"
            f"Напишіть мені будь-що, і я спробую допомогти.\n"
            f"Команди: /help /reset /status /memory /skills /cost"
        )

    async def _cmd_help(self, update, context) -> None:
        await update.message.reply_text(
            "Команди Posipaka:\n\n"
            "/start — привітання\n"
            "/help — ця довідка\n"
            "/reset — скинути сесію\n"
            "/status — статус агента\n"
            "/memory — що я про вас знаю\n"
            "/skills — список навичок\n"
            "/cost — витрати за сьогодні\n\n"
            "Просто надішліть повідомлення — і я відповім!"
        )

    async def _cmd_reset(self, update, context) -> None:
        user_id = str(update.effective_user.id)
        result = await self.agent.handle_command("reset", "", user_id)
        await update.message.reply_text(result)

    async def _cmd_status(self, update, context) -> None:
        user_id = str(update.effective_user.id)
        result = await self.agent.handle_command("status", "", user_id)
        await update.message.reply_text(result)

    async def _cmd_memory(self, update, context) -> None:
        user_id = str(update.effective_user.id)
        result = await self.agent.handle_command("memory", "", user_id)
        await update.message.reply_text(result[:4096])

    async def _cmd_skills(self, update, context) -> None:
        user_id = str(update.effective_user.id)
        result = await self.agent.handle_command("skills", "", user_id)
        await update.message.reply_text(result[:4096])

    async def _cmd_cost(self, update, context) -> None:
        user_id = str(update.effective_user.id)
        result = await self.agent.handle_command("cost", "", user_id)
        await update.message.reply_text(result)

    async def _cmd_persona(self, update, context) -> None:
        user_id = str(update.effective_user.id)
        args = " ".join(context.args) if context.args else ""
        result = await self.agent.handle_command("persona", args, user_id)
        await update.message.reply_text(result[:4096])

    async def _cmd_cron(self, update, context) -> None:
        user_id = str(update.effective_user.id)
        args = " ".join(context.args) if context.args else ""
        result = await self.agent.handle_command("cron", args, user_id)
        await update.message.reply_text(result[:4096])

    async def _cmd_heartbeat(self, update, context) -> None:
        user_id = str(update.effective_user.id)
        result = await self.agent.handle_command("heartbeat", "", user_id)
        await update.message.reply_text(result)

    async def _cmd_setup(self, update, context) -> None:
        """Messenger-based onboarding."""
        user_id = str(update.effective_user.id)

        if not self._is_owner(update.effective_user.id):
            await update.message.reply_text(self._t("system.permission_denied"))
            return

        if self._setup_wizard is None:
            from posipaka.setup.wizard_messenger import MessengerSetupWizard

            self._setup_wizard = MessengerSetupWizard(self.settings)

        result = self._setup_wizard.start_setup(user_id)
        await self._send_setup_response(update, result)

    def _get_reply_context(self, message) -> str:
        """D.3: Extract reply context if user replied to a bot message."""
        if not message.reply_to_message:
            return ""
        reply = message.reply_to_message
        # Check if the replied message is from the bot
        if reply.from_user and self._app and reply.from_user.id == self._app.bot.id:
            original_text = self._reply_cache.get_val(reply.message_id)
            if original_text:
                snippet = original_text[:200]
                return f"[У відповідь на: {snippet}]\n"
        return ""

    async def _send_and_cache(self, update, text: str) -> None:
        """Send response and cache for reply context (D.3)."""
        for part in split_message(text, 4096):
            if "підтвердження" in part.lower() and "так" in part.lower():
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("Підтвердити", callback_data="approve"),
                            InlineKeyboardButton("Відхилити", callback_data="deny"),
                        ]
                    ]
                )
                sent = await update.message.reply_text(part, reply_markup=keyboard)
            else:
                try:
                    sent = await update.message.reply_text(part, parse_mode="Markdown")
                except Exception:
                    sent = await update.message.reply_text(part)
            # Cache for reply context
            if sent:
                self._reply_cache.put(sent.message_id, part)

    async def _check_auth_and_rate(self, update) -> bool:
        """Common auth + rate limit check. Returns True if allowed."""
        user_id = update.effective_user.id
        if not self._is_authorized(user_id):
            await update.message.reply_text(self._t("system.permission_denied"))
            return False
        limiter = self._get_rate_limiter(user_id)
        if not limiter.allow():
            wait = limiter.retry_after()
            await update.message.reply_text(self._t("errors.rate_limit", seconds=f"{wait:.0f}"))
            return False
        return True

    async def _process_and_respond(self, update, text: str) -> None:
        """Process text through agent and send response."""
        user_id = str(update.effective_user.id)
        session = self.agent.sessions.get_or_create(user_id, "telegram")
        await update.message.chat.send_action("typing")

        response_parts = []
        async for chunk in self.agent.handle_message(text, session.id):
            response_parts.append(chunk)

        full_response = "\n".join(response_parts)
        await self._send_and_cache(update, full_response)

    async def _handle_message(self, update, context) -> None:
        """Обробка звичайних повідомлень."""
        if not await self._check_auth_and_rate(update):
            return

        user_id = str(update.effective_user.id)

        # Intercept text input during messenger setup wizard
        if (
            self._setup_wizard
            and self._setup_wizard.is_in_setup(user_id)
            and self._setup_wizard.get_state(user_id).awaiting_input
        ):
            from posipaka.setup.wizard_messenger import build_telegram_keyboard

            result = self._setup_wizard.handle_text_input(user_id, update.message.text)
            keyboard = build_telegram_keyboard(result.get("keyboard"))
            await update.message.reply_text(result["text"], reply_markup=keyboard)
            return

        text = update.message.text

        # D.3: Prepend reply context if replying to bot message
        reply_ctx = self._get_reply_context(update.message)
        if reply_ctx:
            text = reply_ctx + text

        await self._process_and_respond(update, text)

    async def _handle_voice(self, update, context) -> None:
        """D.1: Handle voice/audio messages via STT."""
        if not await self._check_auth_and_rate(update):
            return

        try:
            from posipaka.core.voice import VoiceProcessor
        except ImportError:
            await update.message.reply_text(self._t("system.voice_not_configured"))
            return

        await update.message.chat.send_action("typing")

        # Download voice file
        voice = update.message.voice or update.message.audio or update.message.video_note
        if not voice:
            return

        if voice.file_size and voice.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(self._t("system.file_too_large", max_mb="20"))
            return

        try:
            tg_file = await voice.get_file()
            suffix = ".ogg" if not update.message.video_note else ".mp4"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                await tg_file.download_to_drive(tmp.name)
                tmp_path = Path(tmp.name)

            processor = VoiceProcessor()
            transcription = await processor.transcribe(tmp_path)
            tmp_path.unlink(missing_ok=True)

            if not transcription:
                await update.message.reply_text(self._t("system.voice_failed"))
                return

            # D.3: Add reply context
            reply_ctx = self._get_reply_context(update.message)
            text = f"{reply_ctx}[Голосове повідомлення]: {transcription}"
            await self._process_and_respond(update, text)

        except Exception as e:
            logger.error(f"Voice processing error: {e}")
            await update.message.reply_text(self._t("system.voice_failed"))

    async def _handle_document(self, update, context) -> None:
        """D.2: Handle document uploads (PDF, DOCX, XLSX, text, images)."""
        if not await self._check_auth_and_rate(update):
            return

        doc = update.message.document
        if not doc:
            return

        if doc.file_size and doc.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(self._t("system.file_too_large", max_mb="20"))
            return

        await update.message.chat.send_action("typing")

        try:
            tg_file = await doc.get_file()
            suffix = Path(doc.file_name).suffix if doc.file_name else ""
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                await tg_file.download_to_drive(tmp.name)
                tmp_path = Path(tmp.name)

            extracted = await self._extract_content(tmp_path, doc.mime_type or "")
            tmp_path.unlink(missing_ok=True)

            if not extracted:
                await update.message.reply_text(self._t("system.file_processing_error"))
                return

            # Sanitize external content
            from posipaka.security.injection import sanitize_external_content

            safe_text = sanitize_external_content(extracted[:4000], source="telegram_file")

            caption = update.message.caption or ""
            text = f"[Файл: {doc.file_name}]\n{safe_text}"
            if caption:
                text = f"{caption}\n{text}"

            reply_ctx = self._get_reply_context(update.message)
            if reply_ctx:
                text = reply_ctx + text

            await self._process_and_respond(update, text)

        except Exception as e:
            logger.error(f"Document processing error: {e}")
            await update.message.reply_text(self._t("system.file_processing_error"))

    async def _handle_photo(self, update, context) -> None:
        """D.2: Handle photo messages via Vision API."""
        if not await self._check_auth_and_rate(update):
            return

        photos = update.message.photo
        if not photos:
            return

        await update.message.chat.send_action("typing")

        try:
            # Get largest photo
            photo = photos[-1]
            tg_file = await photo.get_file()
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                await tg_file.download_to_drive(tmp.name)
                tmp_path = Path(tmp.name)

            try:
                from posipaka.core.vision import VisionProcessor

                processor = VisionProcessor()
                analysis = await processor.analyze_image(tmp_path)
            except ImportError:
                analysis = "[Зображення отримано, але Vision API не налаштовано]"

            tmp_path.unlink(missing_ok=True)

            caption = update.message.caption or "Що на цьому зображенні?"
            text = f"{caption}\n[Аналіз зображення]: {analysis}"

            reply_ctx = self._get_reply_context(update.message)
            if reply_ctx:
                text = reply_ctx + text

            await self._process_and_respond(update, text)

        except Exception as e:
            logger.error(f"Photo processing error: {e}")
            await update.message.reply_text(self._t("system.photo_processing_error"))

    async def _extract_content(self, file_path: Path, mime_type: str) -> str:
        """D.2: Extract text content from file based on MIME type."""
        try:
            if mime_type == "application/pdf" or file_path.suffix == ".pdf":
                from posipaka.core.documents import DocumentProcessor

                proc = DocumentProcessor()
                return await proc.process_pdf(file_path)

            elif mime_type in (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/msword",
            ) or file_path.suffix in (".docx", ".doc"):
                from posipaka.core.documents import DocumentProcessor

                proc = DocumentProcessor()
                return await proc.process_docx(file_path)

            elif mime_type in (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-excel",
            ) or file_path.suffix in (".xlsx", ".xls"):
                from posipaka.core.documents import DocumentProcessor

                proc = DocumentProcessor()
                return await proc.process_xlsx(file_path)

            elif mime_type.startswith("image/") or file_path.suffix in (
                ".jpg",
                ".jpeg",
                ".png",
                ".gif",
                ".webp",
            ):
                try:
                    from posipaka.core.vision import VisionProcessor

                    proc = VisionProcessor()
                    return await proc.analyze_image(file_path)
                except ImportError:
                    return "[Зображення: Vision API не налаштовано]"

            elif mime_type.startswith("text/") or file_path.suffix in (
                ".txt",
                ".md",
                ".csv",
                ".json",
                ".yaml",
                ".yml",
                ".py",
                ".js",
            ):
                return file_path.read_text(encoding="utf-8", errors="replace")[:4000]

            else:
                return f"[Файл типу {mime_type} не підтримується для обробки]"

        except Exception as e:
            logger.error(f"Content extraction error: {e}")
            return f"[Помилка обробки: {e}]"

    async def _send_setup_response(self, update, result: dict) -> None:
        """Send setup wizard response with inline keyboard."""
        from posipaka.setup.wizard_messenger import build_telegram_keyboard

        keyboard = build_telegram_keyboard(result.get("keyboard"))
        await update.message.reply_text(
            result["text"],
            reply_markup=keyboard,
        )

    async def _handle_callback(self, update, context) -> None:
        """Обробка inline button callbacks (approval + setup)."""
        query = update.callback_query
        await query.answer()

        user_id = str(query.from_user.id)

        # Setup wizard callbacks
        if query.data and query.data.startswith("setup_"):
            if self._setup_wizard and self._setup_wizard.is_in_setup(user_id):
                from posipaka.setup.wizard_messenger import build_telegram_keyboard

                result = self._setup_wizard.handle_callback(user_id, query.data)
                keyboard = build_telegram_keyboard(result.get("keyboard"))
                await query.edit_message_text(result["text"], reply_markup=keyboard)
                return

        session = self.agent.sessions.get_or_create(user_id, "telegram")

        if query.data == "approve":
            response_parts = []
            async for chunk in self.agent.handle_message("так", session.id):
                response_parts.append(chunk)
            await query.edit_message_text("\n".join(response_parts))
        elif query.data == "deny":
            response_parts = []
            async for chunk in self.agent.handle_message("ні", session.id):
                response_parts.append(chunk)
            await query.edit_message_text("\n".join(response_parts))
