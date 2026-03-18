"""Permission Matrix з runtime changes."""

from __future__ import annotations

import asyncio
from enum import StrEnum

from loguru import logger


class PermissionProfile(StrEnum):
    MINIMAL = "minimal"      # Тільки читання
    STANDARD = "standard"    # Базові дії
    DEVELOPER = "developer"  # Shell, GitHub, файли
    FULL = "full"            # Все
    DOCKER = "docker"        # Docker-safe підмножина


PROFILE_PERMISSIONS: dict[PermissionProfile, set[str]] = {
    PermissionProfile.MINIMAL: {
        "VIEW_AUDIT", "USE_PERSONAS",
    },
    PermissionProfile.STANDARD: {
        "VIEW_AUDIT", "USE_PERSONAS", "USE_VOICE",
        "EMAIL_SEND", "CALENDAR_WRITE",
    },
    PermissionProfile.DEVELOPER: {
        "VIEW_AUDIT", "USE_PERSONAS", "USE_VOICE",
        "EMAIL_SEND", "CALENDAR_WRITE",
        "SHELL_EXEC", "FILE_WRITE", "INSTALL_SKILLS",
    },
    PermissionProfile.FULL: {
        "VIEW_AUDIT", "USE_PERSONAS", "USE_VOICE",
        "EMAIL_SEND", "CALENDAR_WRITE",
        "SHELL_EXEC", "FILE_WRITE", "INSTALL_SKILLS",
        "MANAGE_USERS", "MANAGE_CONFIG",
    },
    PermissionProfile.DOCKER: {
        "VIEW_AUDIT", "USE_PERSONAS", "USE_VOICE",
        "EMAIL_SEND", "CALENDAR_WRITE",
        "FILE_WRITE",
        # No SHELL_EXEC, no MANAGE_CONFIG in Docker
    },
}


class PermissionChecker:
    """Перевірка дозволів перед кожною дією.

    Runtime зміни без рестарту (asyncio.Lock для thread-safety).
    Логує спроби доступу до заборонених ресурсів.
    """

    def __init__(self) -> None:
        self._user_profiles: dict[str, PermissionProfile] = {}
        self._user_overrides: dict[str, set[str]] = {}
        self._user_denials: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def check(
        self,
        user_id: str,
        permission: str,
        resource: str | None = None,
    ) -> bool:
        """Перевірити дозвіл для користувача."""
        async with self._lock:
            allowed = self._get_permissions(user_id)
            # Explicit denials override
            denied = self._user_denials.get(user_id, set())
            if permission in denied:
                logger.warning(
                    f"Permission denied (explicit): {user_id} → {permission}"
                    f"{f' on {resource}' if resource else ''}"
                )
                return False

            if permission in allowed:
                return True

            logger.warning(
                f"Permission denied: {user_id} → {permission}"
                f"{f' on {resource}' if resource else ''}"
            )
            return False

    async def set_profile(self, user_id: str, profile: PermissionProfile) -> None:
        """Встановити профіль дозволів (runtime, без рестарту)."""
        async with self._lock:
            self._user_profiles[user_id] = profile
        logger.info(f"Permission profile set: {user_id} → {profile.value}")

    async def allow(self, user_id: str, permission: str) -> None:
        """Додати окремий дозвіл користувачу."""
        async with self._lock:
            if user_id not in self._user_overrides:
                self._user_overrides[user_id] = set()
            self._user_overrides[user_id].add(permission)
            # Зняти denial якщо був
            self._user_denials.get(user_id, set()).discard(permission)

    async def deny(self, user_id: str, permission: str) -> None:
        """Заборонити конкретний дозвіл."""
        async with self._lock:
            if user_id not in self._user_denials:
                self._user_denials[user_id] = set()
            self._user_denials[user_id].add(permission)

    async def reset(self, user_id: str) -> None:
        """Скинути дозволи до профілю."""
        async with self._lock:
            self._user_overrides.pop(user_id, None)
            self._user_denials.pop(user_id, None)

    async def get_user_permissions(self, user_id: str) -> set[str]:
        """Отримати всі дозволи користувача."""
        async with self._lock:
            return self._get_permissions(user_id)

    def _get_permissions(self, user_id: str) -> set[str]:
        """Розрахувати ефективні дозволи (profile + overrides - denials)."""
        profile = self._user_profiles.get(user_id, PermissionProfile.STANDARD)
        base = set(PROFILE_PERMISSIONS.get(profile, set()))
        overrides = self._user_overrides.get(user_id, set())
        denials = self._user_denials.get(user_id, set())
        return (base | overrides) - denials
