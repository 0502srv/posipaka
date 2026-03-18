"""FilesystemPolicy — scoped access до файлової системи."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from loguru import logger


class AccessDecision(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY_HARD = "deny_hard"


class FilesystemPolicy:
    """
    Контролює доступ агента до файлової системи.

    ALWAYS_ALLOWED  — завжди, без запиту
    REQUIRES_APPROVAL — потрібне явне підтвердження
    ALWAYS_DENIED   — ніколи, навіть з approval
    """

    ALWAYS_DENIED = [
        "~/.ssh/",
        "~/.gnupg/",
        "/etc/shadow",
        "/etc/sudoers",
        "/root/",
        "/var/",
        "/sys/",
        "/proc/",
        "/dev/",
        "~/.aws/",
        "~/.config/gcloud/",
        "~/.kube/",
        "~/.posipaka/.secrets.enc",
        "~/.posipaka/.encryption_key",
        "~/.posipaka/.web_password",
        "~/.posipaka/google_token.json",
    ]

    ALWAYS_ALLOWED = [
        "~/.posipaka/",
        "/tmp/",
    ]

    REQUIRES_APPROVAL_PATHS = [
        "~/Documents/",
        "~/Desktop/",
        "~/Downloads/",
        "~/Projects/",
    ]

    def __init__(self, extra_allowed: list[str] | None = None) -> None:
        self._extra_allowed = [str(Path(p).expanduser().resolve()) for p in (extra_allowed or [])]

    def check_path(self, path: str, operation: str = "read") -> AccessDecision:
        """
        Перевірити доступ до шляху.

        Args:
            path: файловий шлях
            operation: "read" | "write" | "delete" | "chmod"
        """
        try:
            resolved = str(Path(path).expanduser().resolve())
        except (ValueError, OSError):
            return AccessDecision.DENY_HARD

        # 1. Hard deny
        for denied in self.ALWAYS_DENIED:
            denied_resolved = str(Path(denied).expanduser().resolve())
            if resolved.startswith(denied_resolved):
                logger.warning(f"FS deny (hard): {path} → {denied}")
                return AccessDecision.DENY_HARD

        # 2. Always allowed
        for allowed in self.ALWAYS_ALLOWED:
            allowed_resolved = str(Path(allowed).expanduser().resolve())
            if resolved.startswith(allowed_resolved):
                return AccessDecision.ALLOW

        # 3. Extra allowed (from config)
        for extra in self._extra_allowed:
            if resolved.startswith(extra):
                return AccessDecision.ALLOW

        # 4. Write/delete — always approval
        if operation in ("write", "delete", "chmod"):
            return AccessDecision.REQUIRE_APPROVAL

        # 5. Read — check known paths
        for approval_path in self.REQUIRES_APPROVAL_PATHS:
            ap_resolved = str(Path(approval_path).expanduser().resolve())
            if resolved.startswith(ap_resolved):
                return AccessDecision.REQUIRE_APPROVAL

        # Unknown path — approval
        return AccessDecision.REQUIRE_APPROVAL
