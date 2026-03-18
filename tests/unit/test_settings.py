"""Тести для config/settings.py."""

from __future__ import annotations

from posipaka.config.settings import LLMSettings, Settings


def test_settings_defaults():
    """Settings створюються з дефолтними значеннями."""
    settings = Settings()
    assert settings.llm.provider == "mistral"
    assert settings.llm.model == "mistral-large-latest"
    assert settings.soul.name == "Posipaka"
    assert settings.soul.timezone == "Europe/Kyiv"


def test_settings_data_dir(tmp_path, monkeypatch):
    """data_dir створюється коректно."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "test_posipaka"))
    settings = Settings(data_dir=tmp_path / "test_posipaka")
    settings.ensure_data_dir()
    assert settings.data_dir.exists()
    assert (settings.data_dir / "logs").exists()
    assert (settings.data_dir / "skills").exists()


def test_llm_settings_provider_validation():
    """Невалідний провайдер викликає помилку."""
    import pytest

    with pytest.raises(ValueError):
        LLMSettings(provider="invalid_provider")


def test_settings_paths(tmp_path):
    """Перевірка property paths."""
    settings = Settings(data_dir=tmp_path)
    assert settings.soul_md_path == tmp_path / "SOUL.md"
    assert settings.user_md_path == tmp_path / "USER.md"
    assert settings.memory_md_path == tmp_path / "MEMORY.md"
    assert settings.audit_log_path == tmp_path / "audit.log"
    assert settings.sqlite_db_path == tmp_path / "memory.db"
