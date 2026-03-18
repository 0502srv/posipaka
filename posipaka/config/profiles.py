"""Resource profiles — конфігурація під різні VPS розміри."""

from __future__ import annotations

RESOURCE_PROFILES: dict[str, dict] = {
    "minimal": {
        "MEMORY_CHROMA_ENABLED": False,
        "MEMORY_EMBEDDING_MODE": "disabled",
        "BROWSER_STRATEGY": "on_demand",
        "LLM_MAX_TOKENS": 2048,
        "MEMORY_SHORT_TERM_LIMIT": 20,
        "description": "512MB RAM VPS. BM25 пошук. Без векторів.",
    },
    "standard": {
        "MEMORY_CHROMA_ENABLED": True,
        "MEMORY_EMBEDDING_MODE": "scheduled",
        "MEMORY_EMBEDDING_INTERVAL_MINUTES": 15,
        "MEMORY_EMBEDDING_AUTO_UNLOAD": True,
        "BROWSER_STRATEGY": "on_demand",
        "LLM_MAX_TOKENS": 4096,
        "MEMORY_SHORT_TERM_LIMIT": 50,
        "description": "1GB RAM VPS. Гібридний пошук. Batch embedding.",
    },
    "performance": {
        "MEMORY_CHROMA_ENABLED": True,
        "MEMORY_EMBEDDING_MODE": "real_time",
        "MEMORY_EMBEDDING_AUTO_UNLOAD": False,
        "BROWSER_STRATEGY": "pooled",
        "LLM_MAX_TOKENS": 8192,
        "MEMORY_SHORT_TERM_LIMIT": 100,
        "description": "2GB+ RAM. Real-time embedding. Браузерний пул.",
    },
    "local": {
        "MEMORY_CHROMA_ENABLED": True,
        "MEMORY_EMBEDDING_MODE": "real_time",
        "MEMORY_EMBEDDING_AUTO_UNLOAD": False,
        "BROWSER_STRATEGY": "pooled",
        "LLM_MAX_TOKENS": 8192,
        "MEMORY_SHORT_TERM_LIMIT": 200,
        "description": "Локальна машина (8GB+). Максимум.",
    },
}


def get_profile(name: str) -> dict:
    """Отримати профіль за назвою."""
    return RESOURCE_PROFILES.get(name, RESOURCE_PROFILES["standard"])


def list_profiles() -> list[dict]:
    """Список всіх профілів."""
    return [{"name": name, **profile} for name, profile in RESOURCE_PROFILES.items()]
