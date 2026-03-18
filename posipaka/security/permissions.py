"""Multi-user permission model (секція 41 MASTER.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from loguru import logger


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    GUEST = "guest"


class Permission(StrEnum):
    SHELL_EXEC = "shell_exec"
    FILE_WRITE = "file_write"
    EMAIL_SEND = "email_send"
    CALENDAR_WRITE = "calendar_write"
    INSTALL_SKILLS = "install_skills"
    VIEW_AUDIT = "view_audit"
    MANAGE_USERS = "manage_users"
    MANAGE_CONFIG = "manage_config"
    USE_PERSONAS = "use_personas"
    USE_VOICE = "use_voice"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.OWNER: set(Permission),
    Role.ADMIN: set(Permission) - {Permission.MANAGE_CONFIG},
    Role.MEMBER: {
        Permission.EMAIL_SEND,
        Permission.CALENDAR_WRITE,
        Permission.USE_PERSONAS,
        Permission.USE_VOICE,
    },
    Role.GUEST: set(),
}


@dataclass
class UserProfile:
    user_id: str
    channel: str  # telegram | discord | slack | ...
    role: Role = Role.GUEST
    display_name: str = ""
    permissions: set[Permission] = field(default_factory=set)
    custom_permissions: bool = False  # True якщо перевизначено вручну

    def has_permission(self, perm: Permission) -> bool:
        if self.custom_permissions:
            return perm in self.permissions
        return perm in ROLE_PERMISSIONS.get(self.role, set())


class UserManager:
    """Керування користувачами та їх правами."""

    def __init__(self) -> None:
        self._users: dict[str, UserProfile] = {}

    def add_user(
        self,
        user_id: str,
        channel: str,
        role: Role = Role.GUEST,
        display_name: str = "",
    ) -> UserProfile:
        key = f"{channel}:{user_id}"
        profile = UserProfile(
            user_id=user_id,
            channel=channel,
            role=role,
            display_name=display_name,
        )
        self._users[key] = profile
        logger.info(f"User added: {key} as {role}")
        return profile

    def get_user(self, user_id: str, channel: str) -> UserProfile | None:
        return self._users.get(f"{channel}:{user_id}")

    def get_or_create(
        self, user_id: str, channel: str, default_role: Role = Role.GUEST
    ) -> UserProfile:
        profile = self.get_user(user_id, channel)
        if not profile:
            profile = self.add_user(user_id, channel, default_role)
        return profile

    def set_role(self, user_id: str, channel: str, role: Role) -> bool:
        profile = self.get_user(user_id, channel)
        if not profile:
            return False
        profile.role = role
        profile.custom_permissions = False
        return True

    def set_permission(
        self, user_id: str, channel: str, perm: Permission, allowed: bool
    ) -> bool:
        profile = self.get_user(user_id, channel)
        if not profile:
            return False
        if not profile.custom_permissions:
            profile.permissions = ROLE_PERMISSIONS.get(profile.role, set()).copy()
            profile.custom_permissions = True
        if allowed:
            profile.permissions.add(perm)
        else:
            profile.permissions.discard(perm)
        return True

    def remove_user(self, user_id: str, channel: str) -> bool:
        return self._users.pop(f"{channel}:{user_id}", None) is not None

    def list_users(self) -> list[dict]:
        return [
            {
                "user_id": p.user_id,
                "channel": p.channel,
                "role": p.role,
                "display_name": p.display_name,
            }
            for p in self._users.values()
        ]

    def check_permission(
        self, user_id: str, channel: str, perm: Permission
    ) -> bool:
        profile = self.get_user(user_id, channel)
        if not profile:
            return False
        return profile.has_permission(perm)
