"""Smoke tests для post-deploy верифікації (Phase 41)."""

from __future__ import annotations

import subprocess
import sys

import pytest


class TestSmokeBasic:
    """Базові smoke tests — працюють без зовнішніх сервісів."""

    def test_import_posipaka(self):
        """Пакет імпортується без помилок."""
        import posipaka

        assert hasattr(posipaka, "__version__")

    def test_cli_help(self):
        """CLI --help працює."""
        result = subprocess.run(
            [sys.executable, "-m", "posipaka", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "posipaka" in result.stdout.lower() or "usage" in result.stdout.lower()

    def test_settings_load(self):
        """Конфігурація завантажується без crash."""
        from posipaka.config.settings import Settings

        settings = Settings()
        assert settings.llm.provider in ("anthropic", "openai", "ollama")
        assert settings.cost.daily_budget_usd > 0

    def test_security_modules_import(self):
        """Security модулі імпортуються."""
        from posipaka.security.audit import AuditLogger
        from posipaka.security.injection import InjectionDetector
        from posipaka.security.sandbox import ShellSandbox

        assert AuditLogger is not None
        assert InjectionDetector is not None
        assert ShellSandbox is not None

    def test_tool_registry_creation(self):
        """ToolRegistry створюється."""
        from posipaka.core.tools.registry import ToolRegistry

        registry = ToolRegistry()
        assert registry is not None

    def test_memory_manager_import(self):
        """MemoryManager імпортується."""
        from posipaka.memory.manager import MemoryManager

        assert MemoryManager is not None


def _health_available() -> bool:
    try:
        import httpx

        r = httpx.get("http://localhost:8080/api/v1/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


class TestSmokeHealth:
    """Health endpoint smoke test (потребує running server)."""

    @pytest.mark.skipif(
        not _health_available(),
        reason="Server not running",
    )
    def test_health_endpoint(self):
        import httpx

        r = httpx.get("http://localhost:8080/api/v1/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] in ("ok", "degraded")
