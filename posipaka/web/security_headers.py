"""Security headers middleware для FastAPI (з CSP nonces)."""

from __future__ import annotations

import secrets
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Додає security headers до кожної відповіді згідно OWASP.

    CSP nonces для inline scripts замість unsafe-inline.
    Nonce доступний у шаблонах через request.state.csp_nonce.
    """

    async def dispatch(self, request: Request, call_next: Any):
        # Генеруємо nonce для кожного запиту
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}' cdn.tailwindcss.com unpkg.com; "
            "style-src 'self' 'unsafe-inline' cdn.tailwindcss.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        # HSTS тільки якщо HTTPS
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
