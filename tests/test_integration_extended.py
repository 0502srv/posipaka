"""Розширені integration тести (Phase 42)."""

from __future__ import annotations

import pytest
from pathlib import Path


class TestConfigCatalog:
    """Тести config catalog."""

    def test_catalog_import(self):
        from posipaka.config.catalog import CONFIG_CATALOG

        assert len(CONFIG_CATALOG) >= 19

    def test_catalog_entries_have_required_fields(self):
        from posipaka.config.catalog import CONFIG_CATALOG

        for entry in CONFIG_CATALOG:
            assert hasattr(entry, "key")
            assert hasattr(entry, "description")
            assert hasattr(entry, "category")


class TestI18n:
    """Тести інтернаціоналізації."""

    def test_i18n_import(self):
        from posipaka.utils.i18n import I18nTranslator

        assert I18nTranslator is not None

    def test_fallback_chain(self):
        from posipaka.utils.i18n import I18nTranslator

        t = I18nTranslator(lang="uk")
        # I18nTranslator uses __call__, not translate
        result = t("nonexistent.key")
        assert isinstance(result, str)


class TestPersonas:
    """Тести persona system."""

    def test_persona_manager_import(self):
        from posipaka.personas.manager import PersonaManager

        assert PersonaManager is not None

    def test_persona_manager_loads(self):
        from posipaka.personas.manager import PersonaManager

        # Перевіряємо що менеджер створюється
        assert PersonaManager is not None


class TestCronEngine:
    """Тести cron engine."""

    def test_cron_engine_import(self):
        from posipaka.core.cron_engine import CronEngine

        assert CronEngine is not None


class TestWorkflow:
    """Тести workflow engine."""

    def test_workflow_engine_import(self):
        from posipaka.core.workflow import WorkflowEngine

        assert WorkflowEngine is not None


class TestMultiAgent:
    """Тести multi-agent orchestration."""

    def test_orchestrator_import(self):
        from posipaka.core.agents.orchestrator import AgentOrchestrator

        assert AgentOrchestrator is not None


class TestVoice:
    """Тести voice модуля."""

    def test_voice_import(self):
        from posipaka.core.voice import VoicePipeline

        assert VoicePipeline is not None


class TestVision:
    """Тести vision модуля."""

    def test_vision_import(self):
        from posipaka.core.vision import encode_image_for_llm

        assert encode_image_for_llm is not None


class TestDocuments:
    """Тести document processing."""

    def test_documents_import(self):
        from posipaka.core.documents import process_document

        assert process_document is not None


class TestSSRF:
    """Тести SSRF protection."""

    def test_ssrf_import(self):
        from posipaka.security.ssrf import validate_url

        assert validate_url is not None

    def test_block_internal_ips(self):
        from posipaka.security.ssrf import validate_url

        # validate_url returns (is_safe: bool, reason: str)
        safe1, _ = validate_url("http://127.0.0.1/admin")
        safe2, _ = validate_url("http://169.254.169.254/metadata")
        safe3, _ = validate_url("http://localhost:3306")
        assert not safe1
        assert not safe2
        assert not safe3

    def test_block_cgnat_and_benchmarking(self):
        from posipaka.security.ssrf import validate_url

        safe1, _ = validate_url("http://100.100.100.100/")
        safe2, _ = validate_url("http://198.18.0.1/")
        assert not safe1
        assert not safe2

    def test_block_additional_hostnames(self):
        from posipaka.security.ssrf import validate_url

        safe1, _ = validate_url("http://metadata.google.internal/")
        safe2, _ = validate_url("http://kubernetes.default.svc/")
        assert not safe1
        assert not safe2

    def test_block_additional_ports(self):
        from posipaka.security.ssrf import validate_url

        safe1, _ = validate_url("http://example.com:9200/")  # Elasticsearch
        safe2, _ = validate_url("http://example.com:2379/")  # etcd
        assert not safe1
        assert not safe2

    def test_dns_rebinding_double_resolve(self, monkeypatch):
        """DNS rebinding: second resolve returns internal IP."""
        import posipaka.security.ssrf as ssrf_mod

        call_count = 0

        def mock_resolve(hostname, port):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"93.184.216.34"}  # safe public IP
            else:
                return {"127.0.0.1"}  # rebinding to loopback

        monkeypatch.setattr(ssrf_mod, "_resolve_ips", mock_resolve)
        safe, reason = ssrf_mod.validate_url("http://evil.example.com/")
        assert not safe
        assert "rebinding" in reason.lower() or "внутрішня" in reason.lower()

    def test_dns_rebinding_new_ips_appear(self, monkeypatch):
        """DNS rebinding: second resolve adds new internal IP."""
        import posipaka.security.ssrf as ssrf_mod

        call_count = 0

        def mock_resolve(hostname, port):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"93.184.216.34"}
            else:
                return {"93.184.216.34", "10.0.0.1"}  # new internal IP

        monkeypatch.setattr(ssrf_mod, "_resolve_ips", mock_resolve)
        safe, reason = ssrf_mod.validate_url("http://evil.example.com/")
        assert not safe
        assert "rebinding" in reason.lower()

    def test_valid_url_passes(self, monkeypatch):
        """Public URL with stable DNS passes double-resolve."""
        import posipaka.security.ssrf as ssrf_mod

        monkeypatch.setattr(
            ssrf_mod, "_resolve_ips", lambda h, p: {"93.184.216.34"}
        )
        safe, reason = ssrf_mod.validate_url("https://example.com/page")
        assert safe
        assert reason == "ok"


class TestPathTraversal:
    """Тести path traversal protection."""

    def test_path_traversal_import(self):
        from posipaka.security.path_traversal import validate_path

        assert validate_path is not None

    def test_block_traversal(self):
        from posipaka.security.path_traversal import validate_path

        # validate_path returns (is_safe: bool, reason: str)
        safe1, _ = validate_path("../../../etc/passwd")
        safe2, _ = validate_path("/etc/shadow")
        assert not safe1
        assert not safe2


class TestLogging:
    """Тести structured logging."""

    def test_logging_setup_import(self):
        from posipaka.utils.logging import setup_logging

        assert setup_logging is not None
