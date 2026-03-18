"""D.4: Webhook Health & Auto-Recovery.

Periodic self-check of webhook status with automatic re-registration
and fallback to polling mode after consecutive failures.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from posipaka.config.settings import Settings

# Default check interval (seconds)
DEFAULT_CHECK_INTERVAL = 300  # 5 minutes
# Consecutive failures before fallback to polling
MAX_CONSECUTIVE_FAILURES = 3


class WebhookHealthChecker:
    """Monitor webhook health and auto-recover on failure."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._consecutive_failures: dict[str, int] = {}
        self._check_interval = DEFAULT_CHECK_INTERVAL
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start periodic webhook health checking."""
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info(
            f"WebhookHealthChecker started (interval={self._check_interval}s)"
        )

    async def stop(self) -> None:
        """Stop the health checker."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("WebhookHealthChecker stopped")

    async def _check_loop(self) -> None:
        """Periodic check loop."""
        while self._running:
            try:
                await self._check_all_webhooks()
            except Exception as e:
                logger.error(f"Webhook health check error: {e}")
            await asyncio.sleep(self._check_interval)

    async def _check_all_webhooks(self) -> None:
        """Check all configured webhook channels."""
        if (
            self._settings.telegram.use_webhook
            and self._settings.telegram.webhook_url
        ):
            await self._check_telegram_webhook()

    async def _check_telegram_webhook(self) -> None:
        """Check Telegram webhook status and auto-recover."""
        try:
            import httpx

            token = self._settings.telegram.token.get_secret_value()
            if not token:
                return

            url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                data = resp.json()

            if not data.get("ok"):
                self._record_failure("telegram")
                return

            info = data.get("result", {})
            webhook_url = info.get("url", "")
            pending = info.get("pending_update_count", 0)
            last_error = info.get("last_error_message", "")

            if not webhook_url:
                logger.warning("Telegram webhook not set, attempting recovery")
                self._record_failure("telegram")
                await self._recover_telegram_webhook(token)
                return

            if last_error:
                logger.warning(f"Telegram webhook error: {last_error}")
                self._record_failure("telegram")
                await self._recover_telegram_webhook(token)
                return

            if pending > 100:
                logger.warning(
                    f"Telegram webhook has {pending} pending updates"
                )

            # Success — reset counter
            self._consecutive_failures["telegram"] = 0
            logger.debug("Telegram webhook healthy")

        except Exception as e:
            logger.error(f"Telegram webhook check failed: {e}")
            self._record_failure("telegram")

    async def _recover_telegram_webhook(self, token: str) -> None:
        """Re-register Telegram webhook."""
        try:
            import httpx

            webhook_url = self._settings.telegram.webhook_url
            url = f"https://api.telegram.org/bot{token}/setWebhook"

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url,
                    json={
                        "url": f"{webhook_url}/webhooks/telegram",
                        "drop_pending_updates": False,
                    },
                )
                data = resp.json()

            if data.get("ok"):
                logger.info("Telegram webhook re-registered successfully")
                self._consecutive_failures["telegram"] = 0
            else:
                logger.error(f"Webhook re-registration failed: {data}")

        except Exception as e:
            logger.error(f"Webhook recovery failed: {e}")

    def _record_failure(self, channel: str) -> None:
        """Record a failure and check if fallback is needed."""
        count = self._consecutive_failures.get(channel, 0) + 1
        self._consecutive_failures[channel] = count
        logger.warning(
            f"{channel} webhook failure #{count}/{MAX_CONSECUTIVE_FAILURES}"
        )
        if count >= MAX_CONSECUTIVE_FAILURES:
            logger.error(
                f"{channel}: {MAX_CONSECUTIVE_FAILURES} consecutive failures. "
                f"Consider switching to polling mode."
            )

    def get_status(self) -> dict:
        """Get webhook health status for all channels."""
        return {
            "check_interval_seconds": self._check_interval,
            "running": self._running,
            "failures": dict(self._consecutive_failures),
        }
