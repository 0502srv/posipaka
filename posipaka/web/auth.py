"""Web UI Authentication — AuthManager + AuthMiddleware."""

from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import Any

import bcrypt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 300
SESSION_TTL_SECONDS = 3600 * 8
CSRF_TOKEN_LENGTH = 32
MIN_PASSWORD_LENGTH = 12
MAX_CONCURRENT_SESSIONS = 3  # Concurrent session limit per IP


class AuthManager:
    """Менеджер аутентифікації для Web UI."""

    def __init__(self, data_dir: Path) -> None:
        self._password_file = data_dir / ".web_password"
        self._sessions: dict[str, dict[str, Any]] = {}
        self._failed_attempts: dict[str, list[float]] = {}

    def is_configured(self) -> bool:
        return self._password_file.exists()

    def setup_password(self, password: str | None = None) -> str:
        if password is None:
            password = secrets.token_urlsafe(16)
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Пароль має бути >={MIN_PASSWORD_LENGTH} символів")
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        self._password_file.write_bytes(hashed)
        self._password_file.chmod(0o600)
        return password

    def verify_password(self, password: str, client_ip: str) -> bool:
        if self._is_locked_out(client_ip):
            return False
        if not self._password_file.exists():
            return False
        stored_hash = self._password_file.read_bytes()
        is_valid = bcrypt.checkpw(password.encode("utf-8"), stored_hash)
        if not is_valid:
            self._record_failed_attempt(client_ip)
        else:
            self._failed_attempts.pop(client_ip, None)
        return is_valid

    def create_session(self, client_ip: str) -> str:
        # Enforce concurrent session limit per IP
        self._cleanup_expired_sessions()
        ip_sessions = [tok for tok, s in self._sessions.items() if s["ip"] == client_ip]
        if len(ip_sessions) >= MAX_CONCURRENT_SESSIONS:
            # Evict oldest session for this IP
            oldest = min(ip_sessions, key=lambda t: self._sessions[t]["created_at"])
            self._sessions.pop(oldest, None)

        token = secrets.token_urlsafe(32)
        self._sessions[token] = {
            "created_at": time.time(),
            "ip": client_ip,
            "csrf_tokens": [secrets.token_hex(CSRF_TOKEN_LENGTH)],
        }
        return token

    def _cleanup_expired_sessions(self) -> None:
        """Видалити прострочені сесії."""
        now = time.time()
        expired = [
            tok for tok, s in self._sessions.items() if now - s["created_at"] > SESSION_TTL_SECONDS
        ]
        for tok in expired:
            self._sessions.pop(tok, None)

    def validate_session(self, token: str | None) -> bool:
        if not token:
            return False
        session = self._sessions.get(token)
        if not session:
            return False
        if time.time() - session["created_at"] > SESSION_TTL_SECONDS:
            self._sessions.pop(token, None)
            return False
        return True

    def get_csrf_token(self, session_token: str) -> str | None:
        """Return the most recent CSRF token for the session."""
        session = self._sessions.get(session_token)
        if not session:
            return None
        tokens = session.get("csrf_tokens", [])
        return tokens[-1] if tokens else None

    def rotate_csrf_token(self, session_token: str) -> str | None:
        """Generate a new CSRF token and keep last 3."""
        session = self._sessions.get(session_token)
        if not session:
            return None
        new_token = secrets.token_hex(CSRF_TOKEN_LENGTH)
        tokens = session.get("csrf_tokens", [])
        tokens.append(new_token)
        session["csrf_tokens"] = tokens[-3:]
        return new_token

    def validate_csrf(self, session_token: str, csrf_token: str) -> bool:
        session = self._sessions.get(session_token)
        if not session:
            return False
        tokens = session.get("csrf_tokens", [])
        if not tokens:
            return False
        return any(secrets.compare_digest(t, csrf_token) for t in tokens)

    def invalidate_session(self, token: str) -> None:
        self._sessions.pop(token, None)

    def cleanup_old_timestamps(self) -> None:
        """Видалити застарілі записи про невдалі спроби."""
        now = time.time()
        for ip in list(self._failed_attempts):
            recent = [t for t in self._failed_attempts[ip] if now - t < LOCKOUT_DURATION_SECONDS]
            if recent:
                self._failed_attempts[ip] = recent
            else:
                del self._failed_attempts[ip]

    def remaining_lockout_seconds(self, client_ip: str) -> int:
        attempts = self._failed_attempts.get(client_ip, [])
        now = time.time()
        recent = [t for t in attempts if now - t < LOCKOUT_DURATION_SECONDS]
        self._failed_attempts[client_ip] = recent
        if len(recent) < MAX_LOGIN_ATTEMPTS:
            return 0
        return max(0, int(LOCKOUT_DURATION_SECONDS - (now - min(recent))))

    def _is_locked_out(self, client_ip: str) -> bool:
        return self.remaining_lockout_seconds(client_ip) > 0

    def _record_failed_attempt(self, client_ip: str) -> None:
        if client_ip not in self._failed_attempts:
            self._failed_attempts[client_ip] = []
        self._failed_attempts[client_ip].append(time.time())
        if len(self._failed_attempts) > 100:
            self.cleanup_old_timestamps()


class AuthMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware: перевірка автентифікації."""

    EXEMPT_PREFIXES = (
        "/login",
        "/api/v1/health",
        "/api/v1/logout",
        "/webhooks/",
        "/static",
        "/favicon.ico",
    )

    def __init__(self, app: Any, auth_manager: AuthManager) -> None:
        super().__init__(app)
        self.auth = auth_manager

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return await call_next(request)

        # API Bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if self.auth.validate_session(token):
                return await call_next(request)

        # Session cookie
        session_token = request.cookies.get("posipaka_session")
        if session_token and self.auth.validate_session(session_token):
            if request.method in ("POST", "PUT", "DELETE", "PATCH"):
                csrf = request.headers.get("X-CSRF-Token", "")
                if not self.auth.validate_csrf(session_token, csrf):
                    return JSONResponse({"detail": "CSRF validation failed"}, status_code=403)
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return RedirectResponse(url="/login", status_code=303)
