"""Спільні фікстури для тестів Posipaka."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _env_setup(tmp_path, monkeypatch):
    """Встановити тестові env vars щоб Settings не читав реальний .env."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-4-20250514")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / ".posipaka"))
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Тимчасова data_dir для тестів."""
    data_dir = tmp_path / ".posipaka"
    data_dir.mkdir()
    return data_dir
