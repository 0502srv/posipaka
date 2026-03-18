"""Config Catalog — кожне налаштування з поясненням (секція 51 MASTER.md)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConfigEntry:
    key: str
    category: str
    description: str
    effect: str
    type: str  # str | int | float | bool
    default: str
    danger_level: str = "low"  # low | moderate | high
    docs: str = ""


CONFIG_CATALOG: list[ConfigEntry] = [
    # ─── LLM ─────────────────────────────────────────────
    ConfigEntry(
        key="LLM_PROVIDER",
        category="llm",
        description="AI провайдер",
        effect="Де обробляються запити",
        type="str",
        default="anthropic",
        docs="anthropic | openai | ollama",
    ),
    ConfigEntry(
        key="LLM_MODEL",
        category="llm",
        description="Основна модель",
        effect="Розумність та вартість",
        type="str",
        default="claude-sonnet-4-20250514",
    ),
    ConfigEntry(
        key="LLM_FAST_MODEL",
        category="llm",
        description="Модель для простих запитів",
        effect="-70% витрат на прості питання",
        type="str",
        default="claude-haiku-4-5-20251001",
    ),
    ConfigEntry(
        key="LLM_DAILY_BUDGET_USD",
        category="llm",
        description="Денний ліміт витрат (USD)",
        effect="При досягненні — агент зупиняється",
        type="float",
        default="5.0",
        danger_level="moderate",
    ),
    # ─── Heartbeat ─────────────────────────────────────────
    ConfigEntry(
        key="HEARTBEAT_ENABLED",
        category="heartbeat",
        description="Проактивний моніторинг",
        effect="Агент може писати першим",
        type="bool",
        default="false",
    ),
    ConfigEntry(
        key="HEARTBEAT_INTERVAL_MINUTES",
        category="heartbeat",
        description="Інтервал перевірки",
        effect="5хв=$3-10/день, 30хв=$0.5-1/день",
        type="int",
        default="30",
    ),
    ConfigEntry(
        key="HEARTBEAT_ACTIVE_HOURS_START",
        category="heartbeat",
        description="Початок активних годин",
        effect="Без нічних повідомлень",
        type="int",
        default="8",
    ),
    ConfigEntry(
        key="HEARTBEAT_ACTIVE_HOURS_END",
        category="heartbeat",
        description="Кінець активних годин",
        effect="Без нічних повідомлень",
        type="int",
        default="23",
    ),
    # ─── Memory ─────────────────────────────────────────
    ConfigEntry(
        key="MEMORY_BACKEND",
        category="memory",
        description="Тип пам'яті",
        effect="hybrid = семантичний пошук, потребує >512MB RAM",
        type="str",
        default="hybrid",
        docs="sqlite | hybrid",
    ),
    ConfigEntry(
        key="MEMORY_EMBEDDING_MODE",
        category="memory",
        description="Режим embedding",
        effect="scheduled = batch кожні N хв, економить RAM",
        type="str",
        default="scheduled",
        docs="real_time | scheduled | disabled",
    ),
    ConfigEntry(
        key="MEMORY_COMPACTION_THRESHOLD",
        category="memory",
        description="Поріг стиснення розмов",
        effect="Менше = частіше стиснення",
        type="int",
        default="80",
    ),
    # ─── Security ─────────────────────────────────────────
    ConfigEntry(
        key="SECURITY_INJECTION_CHECK",
        category="security",
        description="Захист від prompt injection",
        effect="Блокує маніпуляції в зовнішньому контенті",
        type="bool",
        default="true",
        danger_level="high",
    ),
    ConfigEntry(
        key="SECURITY_CONTAINER_SANDBOX",
        category="security",
        description="Docker sandbox для коду",
        effect="+безпека, +200ms latency",
        type="bool",
        default="false",
    ),
    # ─── Voice ─────────────────────────────────────────
    ConfigEntry(
        key="VOICE_ENABLED",
        category="voice",
        description="Розпізнавання голосових",
        effect="STT через Whisper",
        type="bool",
        default="false",
    ),
    ConfigEntry(
        key="VOICE_TTS_ENABLED",
        category="voice",
        description="Голосові відповіді",
        effect="TTS через edge_tts",
        type="bool",
        default="false",
    ),
    ConfigEntry(
        key="VOICE_REPLY_MODE",
        category="voice",
        description="Режим відповіді",
        effect="Текст та/або голос",
        type="str",
        default="text_only",
        docs="text_only | voice_only | both | auto",
    ),
    # ─── Agent ─────────────────────────────────────────
    ConfigEntry(
        key="SOUL_NAME",
        category="agent",
        description="Ім'я агента",
        effect="Як агент себе називає",
        type="str",
        default="Posipaka",
    ),
    ConfigEntry(
        key="SOUL_LANGUAGE",
        category="agent",
        description="Мова відповідей",
        effect="auto = визначається автоматично",
        type="str",
        default="auto",
        docs="uk | en | auto",
    ),
    ConfigEntry(
        key="RESOURCE_PROFILE",
        category="agent",
        description="Профіль ресурсів",
        effect="Впливає на RAM/CPU usage",
        type="str",
        default="standard",
        docs="minimal | standard | performance | local",
    ),
]


def get_catalog() -> list[ConfigEntry]:
    return CONFIG_CATALOG


def get_by_category(category: str) -> list[ConfigEntry]:
    return [e for e in CONFIG_CATALOG if e.category == category]


def get_categories() -> list[str]:
    return sorted({e.category for e in CONFIG_CATALOG})


def explain(key: str) -> str | None:
    """Детальне пояснення налаштування."""
    for entry in CONFIG_CATALOG:
        if entry.key == key:
            lines = [
                f"{entry.key}",
                f"  Категорія: {entry.category}",
                f"  Опис: {entry.description}",
                f"  Ефект: {entry.effect}",
                f"  Тип: {entry.type}",
                f"  Default: {entry.default}",
            ]
            if entry.docs:
                lines.append(f"  Допустимі: {entry.docs}")
            if entry.danger_level != "low":
                lines.append(f"  Рівень ризику: {entry.danger_level}")
            return "\n".join(lines)
    return None
