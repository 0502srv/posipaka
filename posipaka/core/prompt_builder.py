"""SystemPromptBuilder — збирає system prompt з різних джерел."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from posipaka.core.tools.registry import ToolRegistry
    from posipaka.memory.manager import MemoryManager


RESPONSE_RULES = (
    "КРИТИЧНІ ПРАВИЛА ВІДПОВІДЕЙ (порушення неприпустиме):\n"
    "1. МАКСИМУМ 1500 символів у відповіді. НІКОЛИ не перевищуй цей ліміт.\n"
    "2. ЗАБОРОНЕНО додавати P.S., P.P.S., повторні запрошення, уточнення після відповіді.\n"
    "3. Відповів на питання — ЗУПИНИСЬ. Не питай 'Хочеш ще?', 'Граємо?', 'Твій вибір?'.\n"
    "4. Одна відповідь = одна тема. Без розгалужень на інші теми.\n"
    "5. Не вигадуй посилання, URL, факти. Якщо не знаєш — скажи прямо.\n"
    "6. Якщо потрібна фактична інформація — ОБОВ'ЯЗКОВО використай web_search або wikipedia_search.\n"
    "7. Використовуй структуру (заголовки, списки) для читабельності.\n"
    "8. БЕЗ емодзі, якщо користувач не просить. Максимум 1-2 на повідомлення.\n"
    "9. Не повторюй інформацію яку вже сказав.\n"
    "10. НІКОЛИ не генеруй фейкові URL або посилання на ресурси які не перевірив.\n"
    "11. Використовуй інструменти ТІЛЬКИ за призначенням: web_search — для пошуку, "
    "set_reminder — для нагадувань, get_weather — для погоди. "
    "НІКОЛИ не використовуй write_file, shell_exec або інші файлові/системні інструменти "
    "для створення відповідей користувачу. Відповідай ТЕКСТОМ напряму.\n"
    "12. Якщо користувач надіслав URL — використай web_fetch щоб отримати вміст сторінки, "
    "потім коротко підсумуй основну інформацію ТЕКСТОМ. Не зберігай у файл.\n"
    "13. Якщо в секції 'Пам'ять' або 'Релевантний контекст' є факти про користувача "
    "— ОБОВ'ЯЗКОВО враховуй їх у відповіді. Не ігноруй відомі преференції, ім'я, "
    "контекст попередніх розмов. Звертайся до користувача на ім'я якщо воно відоме."
)


class SystemPromptBuilder:
    """Збирає system prompt з SOUL.md, USER.md, MEMORY.md, skills, rules."""

    def __init__(
        self,
        soul_md_path: Path,
        user_md_path: Path,
        data_dir: Path,
        timezone: str = "UTC",
    ) -> None:
        self.soul_md_path = soul_md_path
        self.user_md_path = user_md_path
        self.data_dir = data_dir
        self.timezone = timezone

    async def build(
        self,
        session_id: str,
        memory: MemoryManager | None = None,
        tools: ToolRegistry | None = None,
        query: str = "",
    ) -> str:
        """Побудова system prompt з усіх джерел."""
        parts = []

        # Current date/time
        try:
            tz = ZoneInfo(self.timezone)
        except (KeyError, ImportError):
            tz = ZoneInfo("UTC")
        now = datetime.now(tz)
        parts.append(
            f"Поточна дата: {now.strftime('%Y-%m-%d %H:%M')} ({now.tzname()})\n\n" + RESPONSE_RULES
        )

        # SOUL.md
        if self.soul_md_path.exists():
            parts.append(self.soul_md_path.read_text(encoding="utf-8"))

        # USER.md
        if self.user_md_path.exists():
            parts.append(self.user_md_path.read_text(encoding="utf-8"))

        # 3-tier memory: CORE (stable) + DYNAMIC (weekly) + MEMORY.md (facts)
        core_path = self.data_dir / "MEMORY-CORE.md"
        dynamic_path = self.data_dir / "MEMORY-DYNAMIC.md"

        if core_path.exists():
            core_content = core_path.read_text(encoding="utf-8").strip()
            if core_content:
                parts.append(core_content)

        if dynamic_path.exists():
            dynamic_content = dynamic_path.read_text(encoding="utf-8").strip()
            if dynamic_content:
                parts.append(dynamic_content)

        # MEMORY.md — auto-extracted facts
        if memory:
            memory_md = memory.get_memory_md()
            if memory_md:
                if len(memory_md) < 2000:
                    parts.append(f"# Пам'ять\n{memory_md}")
                else:
                    relevant_lines = select_relevant_facts(memory_md)
                    if relevant_lines:
                        parts.append(f"# Пам'ять (релевантне)\n{relevant_lines}")

        # Semantic search — relevant context from memory
        if memory and query:
            try:
                relevant = await memory.search_relevant(session_id, query, 5)
                if relevant:
                    parts.append("# Релевантний контекст\n" + "\n".join(relevant))
            except Exception:
                pass  # graceful degradation

        # Skill metadata
        if tools:
            skill_meta = tools.get_skill_metadata()
            if skill_meta:
                parts.append(skill_meta)

        return "\n\n---\n\n".join(parts)

    async def build_cached(
        self,
        session_id: str,
        memory: MemoryManager | None = None,
        tools: ToolRegistry | None = None,
    ) -> list[dict]:
        """Structured system prompt для Anthropic prompt caching."""
        blocks = []

        # BLOCK 1: Статична особистість (кешується)
        if self.soul_md_path.exists():
            blocks.append(
                {
                    "type": "text",
                    "text": self.soul_md_path.read_text(encoding="utf-8"),
                    "cache_control": {"type": "ephemeral"},
                }
            )

        # BLOCK 2: Tools metadata (кешується)
        if tools:
            skill_meta = tools.get_skill_metadata()
            if skill_meta:
                blocks.append(
                    {
                        "type": "text",
                        "text": f"# Available Skills\n{skill_meta}",
                        "cache_control": {"type": "ephemeral"},
                    }
                )

        # BLOCK 3: User profile (кешується)
        if self.user_md_path.exists():
            blocks.append(
                {
                    "type": "text",
                    "text": self.user_md_path.read_text(encoding="utf-8"),
                    "cache_control": {"type": "ephemeral"},
                }
            )

        # BLOCK 4: Динамічна пам'ять (НЕ кешується)
        dynamic_parts = []
        if memory:
            memory_md = memory.get_memory_md()
            if memory_md:
                dynamic_parts.append(memory_md)
            relevant = await memory.search_relevant(session_id, "", 5)
            if relevant:
                dynamic_parts.append("\n".join(relevant))
        if dynamic_parts:
            blocks.append({"type": "text", "text": f"# Context\n{''.join(dynamic_parts)}"})

        return blocks


def select_relevant_facts(memory_md: str) -> str:
    """Вибрати тільки релевантні факти з MEMORY.md."""
    lines = memory_md.strip().split("\n")
    headers = [ln for ln in lines if ln.startswith("#")]
    facts = [ln for ln in lines if ln.strip() and not ln.startswith("#")]

    if len(facts) <= 10:
        return memory_md

    selected = headers + facts[-10:]
    return "\n".join(selected)
