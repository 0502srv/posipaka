"""Skill Sandboxing — статичний аналіз та ізоляція workspace skills (секція 102.9)."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from loguru import logger

ALLOWED_IMPORTS = {
    "json", "re", "datetime", "math", "collections",
    "urllib.parse", "hashlib", "base64", "csv", "io",
    "typing", "dataclasses", "enum", "pathlib",
    "asyncio", "httpx", "aiofiles",
    "posipaka",
}

DENIED_IMPORTS = {
    "os", "sys", "subprocess", "shutil", "ctypes", "importlib",
    "socket", "http.server", "xmlrpc", "multiprocessing",
    "signal", "resource", "pty", "fcntl", "termios",
    "code", "codeop", "compile", "compileall",
    "pickle", "shelve", "marshal",
}


class SkillSecurityError(Exception):
    pass


class SkillSandbox:
    """Перевірка та ізоляція workspace skills."""

    @staticmethod
    def validate_skill_source(tools_py_path: Path) -> list[str]:
        """Статичний аналіз tools.py. Порожній список = безпечно."""
        source = tools_py_path.read_text(encoding="utf-8")
        violations: list[str] = []

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return [f"Syntax error: {e}"]

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split(".")[0]
                    if module in DENIED_IMPORTS:
                        violations.append(
                            f"Заборонений import: '{alias.name}' "
                            f"(рядок {node.lineno})"
                        )

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module = node.module.split(".")[0]
                    if module in DENIED_IMPORTS:
                        violations.append(
                            f"Заборонений from import: '{node.module}' "
                            f"(рядок {node.lineno})"
                        )

            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("eval", "exec", "compile", "__import__")
            ):
                violations.append(
                    f"Заборонена функція: '{node.func.id}()' "
                    f"(рядок {node.lineno})"
                )

            elif (
                isinstance(node, ast.Attribute)
                and node.attr.startswith("__")
                and node.attr.endswith("__")
                and node.attr not in ("__init__", "__str__", "__repr__", "__len__")
            ):
                violations.append(
                    f"Підозрілий dunder: '{node.attr}' "
                    f"(рядок {node.lineno})"
                )

        return violations

    @staticmethod
    def compute_skill_hash(skill_dir: Path) -> str:
        """SHA-256 hash всіх файлів skill."""
        h = hashlib.sha256()
        for filepath in sorted(skill_dir.rglob("*")):
            if filepath.is_file() and filepath.name != "skill.lock":
                h.update(filepath.name.encode())
                h.update(filepath.read_bytes())
        return h.hexdigest()

    @staticmethod
    def create_lock_file(skill_dir: Path) -> None:
        hash_value = SkillSandbox.compute_skill_hash(skill_dir)
        lock_file = skill_dir / "skill.lock"
        lock_file.write_text(f"sha256:{hash_value}\n")
        logger.info(f"Lock created: {skill_dir.name}")

    @staticmethod
    def verify_lock_file(skill_dir: Path) -> bool:
        lock_file = skill_dir / "skill.lock"
        if not lock_file.exists():
            return True
        expected = lock_file.read_text().strip()
        actual = f"sha256:{SkillSandbox.compute_skill_hash(skill_dir)}"
        return expected == actual
