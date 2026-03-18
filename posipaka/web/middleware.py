"""Request validation middleware."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024
MAX_CONCURRENT_REQUESTS = 50
MAX_INPUT_LENGTH = 8_000
MAX_UPLOAD_SIZE = 20 * 1024 * 1024
MAX_FILE_PAGES = 50
ALLOWED_FILE_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".pdf",
    ".docx",
    ".xlsx",
    ".py",
    ".js",
    ".html",
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
}


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """Thread-safe request validation з asyncio.Semaphore."""

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_REQUEST_BODY_BYTES:
                    return JSONResponse({"detail": "Request too large"}, status_code=413)
            except ValueError:
                pass

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=0.01)
        except TimeoutError:
            return JSONResponse({"detail": "Server overloaded"}, status_code=503)

        try:
            return await call_next(request)
        finally:
            self._semaphore.release()


class WebhookRateLimiter(BaseHTTPMiddleware):
    """
    Rate limiting для webhook endpoints.
    Sliding window per IP. Default: 120 req/min.
    """

    def __init__(
        self,
        app: Any,
        max_requests: int = 120,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self._max = max_requests
        self._window = window_seconds
        self._requests: dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/webhooks/"):
            return await call_next(request)

        import time

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # Cleanup old
        if client_ip not in self._requests:
            self._requests[client_ip] = []
        self._requests[client_ip] = [t for t in self._requests[client_ip] if now - t < self._window]

        if len(self._requests[client_ip]) >= self._max:
            return JSONResponse(
                {"detail": "Too many requests"},
                status_code=429,
                headers={"Retry-After": str(self._window)},
            )

        self._requests[client_ip].append(now)
        return await call_next(request)


def validate_message_length(content: str) -> tuple[bool, str]:
    if len(content) > MAX_INPUT_LENGTH:
        return False, (
            f"Повідомлення занадто довге: {len(content)} символів "
            f"(максимум {MAX_INPUT_LENGTH}). Спробуйте коротше або надішліть як файл."
        )
    return True, "ok"


def validate_file_upload(filename: str, size_bytes: int) -> tuple[bool, str]:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_FILE_EXTENSIONS:
        return False, f"Тип файлу '{ext}' не підтримується."
    if size_bytes > MAX_UPLOAD_SIZE:
        mb = size_bytes // (1024 * 1024)
        max_mb = MAX_UPLOAD_SIZE // (1024 * 1024)
        return False, f"Файл занадто великий: {mb} MB (макс {max_mb} MB)."
    return True, "ok"
