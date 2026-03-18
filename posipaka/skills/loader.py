"""SkillLoader — сканує та завантажує скіли з директорій."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


@dataclass
class SkillDefinition:
    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    category: str = "skill"
    version: str = "1.0.0"
    requires_env: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    path: Path | None = None


class SkillLoader:
    """Завантажує скіли з директорій."""

    def scan_directory(self, path: Path) -> list[SkillDefinition]:
        """Сканувати директорію на наявність скілів."""
        skills = []
        if not path.exists():
            return skills

        for skill_dir in path.iterdir():
            if not skill_dir.is_dir():
                continue
            if (skill_dir / "tools.py").exists():
                skill_def = self.load_skill(skill_dir)
                if skill_def:
                    skills.append(skill_def)

        return skills

    def load_skill(self, path: Path) -> SkillDefinition | None:
        """Завантажити окремий скіл з директорії."""
        skill_md = path / "SKILL.md"
        if not skill_md.exists():
            # No SKILL.md — use directory name
            return SkillDefinition(
                name=path.name,
                description=f"Skill: {path.name}",
                path=path,
            )

        try:
            content = skill_md.read_text(encoding="utf-8")
            metadata = self._parse_frontmatter(content)
            return SkillDefinition(
                name=metadata.get("name", path.name),
                description=metadata.get("description", ""),
                triggers=metadata.get("triggers", []),
                category=metadata.get("category", "skill"),
                version=metadata.get("version", "1.0.0"),
                requires_env=metadata.get("requires_env", []),
                tags=metadata.get("tags", []),
                path=path,
            )
        except Exception as e:
            logger.warning(f"Error loading skill {path.name}: {e}")
            return None

    def load_into_registry(self, skill_def: SkillDefinition, registry: Any) -> None:
        """Завантажити tools.py скілу в registry."""
        if not skill_def.path:
            return
        registry.load_skill_dir(skill_def.path)

    @staticmethod
    def _parse_frontmatter(content: str) -> dict:
        """Парсити YAML frontmatter з SKILL.md."""
        if not content.startswith("---"):
            return {}
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}
        try:
            return yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            return {}
