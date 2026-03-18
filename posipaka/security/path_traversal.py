"""Path Traversal Protection — блокування доступу поза дозволеними директоріями."""

from __future__ import annotations

from pathlib import Path

BLOCKED_PATHS = {
    "/etc/shadow",
    "/etc/passwd",
    "/etc/sudoers",
    "/root",
    "/proc",
    "/sys",
}

BLOCKED_PATTERNS = [
    "..",
    "~root",
    "/etc/shadow",
    "/proc/self",
]


def validate_path(
    path: str,
    allowed_dirs: list[str] | None = None,
    data_dir: str | None = None,
) -> tuple[bool, str]:
    """
    Перевірити шлях на path traversal.

    Args:
        path: Шлях для перевірки
        allowed_dirs: Дозволені директорії (якщо пусто — дозволяємо все крім blocked)
        data_dir: ~/.posipaka — завжди дозволена

    Returns: (safe, reason)
    """
    try:
        resolved = Path(path).expanduser().resolve()
        resolved_str = str(resolved)

        # Check blocked paths
        for blocked in BLOCKED_PATHS:
            if resolved_str.startswith(blocked):
                return False, f"Заблокований шлях: {blocked}"

        # Check blocked patterns in original input
        for pattern in BLOCKED_PATTERNS:
            if pattern in path:
                return False, f"Підозрілий патерн: {pattern}"

        # If allowed_dirs specified — restrict to those
        if allowed_dirs:
            dirs = [Path(d).expanduser().resolve() for d in allowed_dirs]
            if data_dir:
                dirs.append(Path(data_dir).expanduser().resolve())
            dirs.append(Path("/tmp").resolve())

            if not any(
                resolved_str.startswith(str(d)) for d in dirs
            ):
                return False, (
                    f"Шлях {resolved} поза дозволеними директоріями"
                )

        return True, "ok"

    except Exception as e:
        return False, f"Невалідний шлях: {e}"
