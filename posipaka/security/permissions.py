"""Multi-user permission model."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

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
    """Керування користувачами та їх правами з persistence."""

    def __init__(self, persist_path: Path | None = None) -> None:
        self._users: dict[str, UserProfile] = {}
        self._persist_path = persist_path
        self._load()

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
        self._save()
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
        self._save()
        return True

    def set_permission(self, user_id: str, channel: str, perm: Permission, allowed: bool) -> bool:
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
        self._save()
        return True

    def remove_user(self, user_id: str, channel: str) -> bool:
        removed = self._users.pop(f"{channel}:{user_id}", None) is not None
        if removed:
            self._save()
        return removed

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

    def check_permission(self, user_id: str, channel: str, perm: Permission) -> bool:
        profile = self.get_user(user_id, channel)
        if not profile:
            return False
        return profile.has_permission(perm)

    def _save(self) -> None:
        """Persist users to JSON file."""
        if not self._persist_path:
            return
        try:
            data = []
            for _key, p in self._users.items():
                entry: dict = {
                    "user_id": p.user_id,
                    "channel": p.channel,
                    "role": p.role.value,
                    "display_name": p.display_name,
                }
                if p.custom_permissions:
                    entry["permissions"] = [perm.value for perm in p.permissions]
                data.append(entry)
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug(f"UserManager save failed: {e}")

    def _load(self) -> None:
        """Load users from JSON file."""
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for entry in data:
                role = Role(entry.get("role", "guest"))
                profile = UserProfile(
                    user_id=entry["user_id"],
                    channel=entry["channel"],
                    role=role,
                    display_name=entry.get("display_name", ""),
                )
                if "permissions" in entry:
                    profile.custom_permissions = True
                    profile.permissions = {Permission(p) for p in entry["permissions"]}
                key = f"{profile.channel}:{profile.user_id}"
                self._users[key] = profile
            if self._users:
                logger.debug(f"UserManager: loaded {len(self._users)} users from disk")
        except Exception as e:
            logger.debug(f"UserManager load failed: {e}")
