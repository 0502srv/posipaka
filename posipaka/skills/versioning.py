"""Skill versioning, verification, and registry."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from posipaka.skills.loader import SkillDefinition


@dataclass
class VersionConstraint:
    """Semver constraint for skill dependencies."""

    min_version: str
    max_version: str | None = None


class SkillVersion:
    """Semver parsing, comparison, and compatibility checks."""

    _SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

    @classmethod
    def parse(cls, version_str: str) -> tuple[int, int, int]:
        """Parse a semver string into (major, minor, patch).

        Raises ValueError if format is invalid.
        """
        m = cls._SEMVER_RE.match(version_str.strip())
        if not m:
            raise ValueError(f"Invalid semver: {version_str!r}")
        return int(m.group(1)), int(m.group(2)), int(m.group(3))

    @classmethod
    def compare(cls, v1: str, v2: str) -> int:
        """Compare two semver strings. Returns -1, 0, or 1."""
        t1 = cls.parse(v1)
        t2 = cls.parse(v2)
        if t1 < t2:
            return -1
        if t1 > t2:
            return 1
        return 0

    @classmethod
    def satisfies(cls, version: str, constraint: VersionConstraint) -> bool:
        """Check if version satisfies a VersionConstraint (min <= version <= max)."""
        if cls.compare(version, constraint.min_version) < 0:
            return False
        return not (
            constraint.max_version is not None
            and cls.compare(version, constraint.max_version) > 0
        )

    @classmethod
    def is_compatible(cls, current: str, required: str) -> bool:
        """Check semver compatibility — major versions must match, current >= required."""
        cur = cls.parse(current)
        req = cls.parse(required)
        if cur[0] != req[0]:
            return False
        # Within the same major, current must be >= required
        return cur >= req


class SkillVerifier:
    """Integrity checks, lock files, dependency validation, and hashing for skills."""

    def verify_integrity(self, skill_dir: Path) -> tuple[bool, str]:
        """Verify that a skill directory is structurally valid.

        Checks:
        - Directory exists
        - tools.py exists
        - SKILL.md exists and has valid YAML frontmatter with required fields
        """
        if not skill_dir.is_dir():
            return False, f"Directory does not exist: {skill_dir}"

        tools_py = skill_dir / "tools.py"
        if not tools_py.exists():
            return False, f"Missing tools.py in {skill_dir.name}"

        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return False, f"Missing SKILL.md in {skill_dir.name}"

        # Validate SKILL.md frontmatter
        try:
            content = skill_md.read_text(encoding="utf-8")
            if not content.startswith("---"):
                return False, f"SKILL.md in {skill_dir.name} has no YAML frontmatter"

            parts = content.split("---", 2)
            if len(parts) < 3:
                return False, f"SKILL.md in {skill_dir.name} has malformed frontmatter"

            import yaml

            metadata = yaml.safe_load(parts[1]) or {}
            if not metadata.get("name"):
                return False, f"SKILL.md in {skill_dir.name} missing 'name' field"
            if not metadata.get("description"):
                return False, f"SKILL.md in {skill_dir.name} missing 'description' field"

        except Exception as e:
            return False, f"Error reading SKILL.md in {skill_dir.name}: {e}"

        logger.debug("Skill integrity OK: {}", skill_dir.name)
        return True, "ok"

    def verify_lock(self, skill_dir: Path) -> bool:
        """Check if skill.lock exists (indicates manually verified skill)."""
        lock_path = skill_dir / "skill.lock"
        return lock_path.is_file()

    def create_lock(self, skill_dir: Path) -> None:
        """Create skill.lock with timestamp and SHA-256 hash of tools.py."""
        content_hash = self.compute_hash(skill_dir)
        lock_data = {
            "locked_at": time.time(),
            "locked_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tools_hash": content_hash,
        }
        lock_path = skill_dir / "skill.lock"
        lock_path.write_text(json.dumps(lock_data, indent=2), encoding="utf-8")
        logger.info("Created skill.lock for {}", skill_dir.name)

    def check_dependencies(
        self,
        skill_def: SkillDefinition,
        available_skills: list[SkillDefinition],
    ) -> list[str]:
        """Return list of missing dependency names.

        Dependencies are read from skill_def.requires_env as a simple name list.
        Any name not found in available_skills is reported as missing.
        """
        available_names = {s.name for s in available_skills}
        missing: list[str] = []
        for dep in skill_def.requires_env:
            if dep not in available_names:
                missing.append(dep)
        return missing

    def compute_hash(self, skill_dir: Path) -> str:
        """Compute SHA-256 hex digest of tools.py content."""
        tools_py = skill_dir / "tools.py"
        if not tools_py.exists():
            return ""
        data = tools_py.read_bytes()
        return hashlib.sha256(data).hexdigest()


class SkillRegistry:
    """Extended skill registry with version-aware operations."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._versions: dict[str, dict[str, SkillDefinition]] = {}

    def register(self, skill: SkillDefinition) -> None:
        """Register a skill definition. Overwrites if same name+version exists."""
        self._skills[skill.name] = skill
        # Also index by version
        if skill.name not in self._versions:
            self._versions[skill.name] = {}
        self._versions[skill.name][skill.version] = skill
        logger.debug("Registered skill {}@{}", skill.name, skill.version)

    def get(self, name: str) -> SkillDefinition | None:
        """Get the latest registered skill by name."""
        return self._skills.get(name)

    def list_skills(self, category: str | None = None) -> list[SkillDefinition]:
        """List all registered skills, optionally filtered by category."""
        skills = list(self._skills.values())
        if category is not None:
            skills = [s for s in skills if s.category == category]
        return skills

    def check_updates(self, skill: SkillDefinition, available_version: str) -> bool:
        """Return True if available_version is newer than the skill's current version."""
        try:
            return SkillVersion.compare(available_version, skill.version) > 0
        except ValueError:
            logger.warning(
                "Invalid version comparing {}@{} with {}",
                skill.name,
                skill.version,
                available_version,
            )
            return False

    def get_by_version(self, name: str, version: str) -> SkillDefinition | None:
        """Get a specific version of a skill."""
        versions = self._versions.get(name, {})
        return versions.get(version)
