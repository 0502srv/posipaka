"""PersonaManager — керування спеціалізованими персонами."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from loguru import logger

SAFETY_DISCLAIMERS: dict[str, str] = {
    "medical": ("Загальна інформація, не медична порада. При симптомах — зверніться до лікаря."),
    "financial": "Не фінансова консультація ліцензованого радника.",
    "legal": "Не юридична консультація. Зверніться до адвоката.",
    "psych": ("Не психотерапевт. При серйозних проблемах — зверніться до спеціаліста."),
}


@dataclass
class PersonaDefinition:
    name: str
    display_name: str = ""
    description: str = ""
    category: str = "general"
    version: str = "1.0.0"
    safety_level: str = "low"  # low | moderate | high | medical
    requires_tools: list[str] = field(default_factory=list)
    optional_tools: list[str] = field(default_factory=list)
    memory_scope: str = "persona"  # persona | shared
    activation_keywords: list[str] = field(default_factory=list)
    soul_content: str = ""
    knowledge_content: str = ""
    disclaimer: str = ""
    path: Path | None = None


class PersonaManager:
    """Завантаження, активація та перемикання персон."""

    def __init__(self, data_dir: Path, builtin_dir: Path | None = None) -> None:
        self._data_dir = data_dir
        self._user_dir = data_dir / "personas"
        self._builtin_dir = builtin_dir or (Path(__file__).parent / "builtin")
        self._personas: dict[str, PersonaDefinition] = {}
        self._active: str | None = None

    def scan(self) -> list[PersonaDefinition]:
        """Сканувати всі директорії на персони."""
        self._personas.clear()

        for directory in [self._builtin_dir, self._user_dir]:
            if not directory.exists():
                continue
            for persona_dir in directory.iterdir():
                if not persona_dir.is_dir():
                    continue
                persona_md = persona_dir / "PERSONA.md"
                if not persona_md.exists():
                    continue
                p = self._load_persona(persona_dir)
                if p:
                    self._personas[p.name] = p

        logger.info(f"Loaded {len(self._personas)} personas")
        return list(self._personas.values())

    def _load_persona(self, path: Path) -> PersonaDefinition | None:
        """Завантажити одну персону з директорії."""
        try:
            persona_md = path / "PERSONA.md"
            content = persona_md.read_text(encoding="utf-8")
            metadata = self._parse_frontmatter(content)
            body = self._strip_frontmatter(content)

            knowledge = ""
            knowledge_path = path / "KNOWLEDGE.md"
            if knowledge_path.exists():
                knowledge = knowledge_path.read_text(encoding="utf-8")

            safety = metadata.get("safety_level", "low")
            disclaimer = SAFETY_DISCLAIMERS.get(safety, "")

            return PersonaDefinition(
                name=metadata.get("name", path.name),
                display_name=metadata.get("display_name", path.name),
                description=metadata.get("description", ""),
                category=metadata.get("category", "general"),
                version=metadata.get("version", "1.0.0"),
                safety_level=safety,
                requires_tools=metadata.get("requires_tools", []),
                optional_tools=metadata.get("optional_tools", []),
                memory_scope=metadata.get("memory_scope", "persona"),
                activation_keywords=metadata.get("activation_keywords", []),
                soul_content=body,
                knowledge_content=knowledge,
                disclaimer=disclaimer,
                path=path,
            )
        except Exception as e:
            logger.warning(f"Error loading persona {path.name}: {e}")
            return None

    def activate(self, name: str) -> PersonaDefinition | None:
        """Активувати персону."""
        persona = self._personas.get(name)
        if not persona:
            return None
        self._active = name
        logger.info(f"Persona activated: {persona.display_name}")
        return persona

    def deactivate(self) -> None:
        """Повернутись до звичайного Posipaka."""
        if self._active:
            logger.info(f"Persona deactivated: {self._active}")
        self._active = None

    @property
    def active(self) -> PersonaDefinition | None:
        if self._active:
            return self._personas.get(self._active)
        return None

    def list_personas(self) -> list[dict]:
        return [
            {
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "category": p.category,
                "active": p.name == self._active,
            }
            for p in self._personas.values()
        ]

    def match_keywords(self, text: str) -> PersonaDefinition | None:
        """Знайти персону по ключових словах."""
        lower = text.lower()
        for persona in self._personas.values():
            for keyword in persona.activation_keywords:
                if keyword.lower() in lower:
                    return persona
        return None

    def get_system_prompt_addon(self) -> str:
        """Додаток до system prompt якщо персона активна."""
        persona = self.active
        if not persona:
            return ""

        parts = [f"\n# Active Persona: {persona.display_name}\n"]
        if persona.soul_content:
            parts.append(persona.soul_content)
        if persona.knowledge_content:
            parts.append(f"\n# Knowledge Base\n{persona.knowledge_content}")
        if persona.disclaimer:
            parts.append(f"\n# DISCLAIMER (додавати до кожної відповіді)\n{persona.disclaimer}")

        return "\n".join(parts)

    @staticmethod
    def _parse_frontmatter(content: str) -> dict:
        if not content.startswith("---"):
            return {}
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}
        try:
            return yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            return {}

    @staticmethod
    def _strip_frontmatter(content: str) -> str:
        if not content.startswith("---"):
            return content
        parts = content.split("---", 2)
        return parts[2].strip() if len(parts) >= 3 else content
