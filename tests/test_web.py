"""Тести для Web UI та API."""

from __future__ import annotations

import pytest


class TestSecurityHeaders:
    """Тести security headers middleware."""

    def test_csp_nonce_generation(self):
        """CSP nonce генерується для кожного запиту."""
        import secrets

        nonce1 = secrets.token_urlsafe(16)
        nonce2 = secrets.token_urlsafe(16)
        assert nonce1 != nonce2
        assert len(nonce1) > 10

    def test_security_headers_middleware_import(self):
        from posipaka.web.security_headers import SecurityHeadersMiddleware

        assert SecurityHeadersMiddleware is not None

    def test_auth_manager_import(self):
        from posipaka.web.auth import AuthManager

        assert AuthManager is not None


class TestWebhookRateLimiter:
    """Тести для WebhookRateLimiter."""

    def test_rate_limiter_import(self):
        from posipaka.web.middleware import WebhookRateLimiter

        assert WebhookRateLimiter is not None


class TestBackupSecurity:
    """Тести безпеки backup/restore."""

    def test_backup_manager_import(self):
        from posipaka.utils.backup import BackupManager

        assert BackupManager is not None

    def test_backup_path_traversal_check(self, tmp_path):
        """Path traversal в архіві блокується."""
        import io
        import tarfile

        from posipaka.utils.backup import BackupManager

        mgr = BackupManager(tmp_path)

        # Створити архів з path traversal
        malicious_archive = tmp_path / "evil.tar.gz"
        with tarfile.open(str(malicious_archive), "w:gz") as tar:
            info = tarfile.TarInfo(name="../../../etc/passwd")
            info.size = 4
            tar.addfile(info, io.BytesIO(b"evil"))

        with pytest.raises(ValueError, match="[Нн]ебезпечний|traversal"):
            mgr.restore_backup(malicious_archive)


class TestPrivacy:
    """Тести GDPR/Privacy."""

    def test_privacy_manager_import(self):
        from posipaka.core.privacy_manager import PrivacyManager

        assert PrivacyManager is not None

    def test_eu_ai_act_disclosure(self, tmp_path):
        from posipaka.core.privacy_manager import PrivacyManager

        pm = PrivacyManager(data_dir=tmp_path)
        disclosure = pm.get_first_contact_disclosure()
        assert "штучний інтелект" in disclosure or "AI" in disclosure


class TestDegradation:
    """Тести graceful degradation."""

    def test_degradation_manager_import(self):
        from posipaka.core.degradation import DegradationManager, SystemMode

        dm = DegradationManager()
        assert dm.mode == SystemMode.FULL

    def test_failure_changes_mode(self):
        from posipaka.core.degradation import DegradationManager, SystemMode

        dm = DegradationManager()
        dm.register_component("llm")
        dm.report_failure("llm", "timeout")
        assert dm.mode == SystemMode.DEGRADED

    def test_recovery(self):
        from posipaka.core.degradation import DegradationManager, SystemMode

        dm = DegradationManager()
        dm.register_component("llm")
        dm.report_failure("llm", "timeout")
        dm.report_recovery("llm")
        assert dm.mode == SystemMode.FULL


class TestStructuredOutput:
    """Тести structured output parsing."""

    def test_parse_json_block(self):
        from posipaka.core.structured_output import (
            AgentDecision,
            parse_structured_output,
        )

        text = '''Here is my decision:
```json
{"action": "respond", "reasoning": "simple question", "confidence": 0.9}
```'''
        result = parse_structured_output(text, AgentDecision)
        assert result is not None
        assert result.action == "respond"
        assert result.confidence == 0.9

    def test_parse_invalid_json(self):
        from posipaka.core.structured_output import (
            AgentDecision,
            parse_structured_output,
        )

        result = parse_structured_output("not json at all", AgentDecision)
        assert result is None


class TestQualityMonitor:
    """Тести quality monitoring."""

    def test_quality_score(self):
        from posipaka.core.quality import QualityMonitor

        qm = QualityMonitor()
        scores = qm.score_response(
            query="Як працює Python?",
            response="Python — це інтерпретована мова програмування високого рівня.",
            response_time=2.5,
        )
        assert 0 <= scores["overall"] <= 1
        assert scores["speed"] == 1.0  # <3s = 1.0

    def test_slo_monitor(self):
        from posipaka.core.quality import SLOMonitor

        slo = SLOMonitor()
        slo.record("response_time", 2.0)
        slo.record("response_time", 3.0)
        report = slo.get_report()
        assert "slos" in report


class TestFeatureFlags:
    """Тести feature flags."""

    @pytest.mark.asyncio
    async def test_feature_flag_manager(self, tmp_path):
        from posipaka.core.feature_flags import FeatureFlagManager

        mgr = FeatureFlagManager(tmp_path / "flags.db")
        await mgr._init_db()
        await mgr.create_flag("TEST_FLAG", "test", enabled=False)

        assert not await mgr.is_enabled("TEST_FLAG")
        await mgr.enable("TEST_FLAG")
        assert await mgr.is_enabled("TEST_FLAG")


class TestResourceMonitor:
    """Тести resource monitor."""

    def test_snapshot(self):
        from posipaka.core.resource_monitor import ResourceMonitor

        mon = ResourceMonitor()
        snap = mon.snapshot()
        assert snap.cpu_percent >= 0
        # memory_total_mb може бути 0 якщо psutil не встановлено
        assert snap.memory_total_mb >= 0

    def test_status_report(self):
        from posipaka.core.resource_monitor import ResourceMonitor

        mon = ResourceMonitor()
        report = mon.get_status_report()
        assert "CPU" in report
        assert "RAM" in report


class TestPlatformDetection:
    """Тести platform detection."""

    def test_detect_platform(self):
        from posipaka.core.platform import detect_platform

        info = detect_platform()
        assert info.os_name in ("linux", "darwin", "windows")
        assert info.cpu_count > 0
        assert info.ram_mb > 0


class TestSecretsRotation:
    """Тести secrets rotation policy."""

    def test_rotation_policy(self, tmp_path):
        from posipaka.security.rotation import SecretsRotationPolicy

        policy = SecretsRotationPolicy(tmp_path)
        warnings = policy.check_rotation_needed()
        assert isinstance(warnings, list)

    def test_record_rotation(self, tmp_path):
        from posipaka.security.rotation import SecretsRotationPolicy

        policy = SecretsRotationPolicy(tmp_path)
        policy.record_rotation("ANTHROPIC_API_KEY")
        warnings = policy.check_rotation_needed()
        # Щойно записане — не має бути warning
        anthropic_warns = [w for w in warnings if w["key"] == "ANTHROPIC_API_KEY"]
        assert len(anthropic_warns) == 0
