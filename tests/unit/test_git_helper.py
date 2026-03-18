"""Тести для git_helper skill — secret scanning, hygiene, history audit."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from posipaka.skills.builtin.git_helper.tools import (
    AI_TRACE_PATTERN,
    SECRET_PATTERNS,
    git_secret_scan,
)


class TestSecretPatterns:
    """Перевірка що всі secret patterns спрацьовують."""

    @pytest.mark.parametrize(
        "secret,label",
        [
            ("sk-ant-abc123def456ghi789jkl", "Anthropic API Key"),
            ("sk-abcdefghijklmnopqrstuvwxyz", "OpenAI API Key"),
            ("AKIAIOSFODNN7EXAMPLE", "AWS Access Key"),
            ("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij", "GitHub PAT"),
            ("gho_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij", "GitHub OAuth"),
            ("glpat-abcdefghijklmnopqrst", "GitLab PAT"),
            ("xoxb-123-456-abcdef", "Slack Bot Token"),
            ("xoxp-123-456-abcdef", "Slack User Token"),
            ("123456789:ABCdefGHIjklMNOpqrSTUvwxyz12345678a", "Telegram Bot Token"),
            ("-----BEGIN RSA PRIVATE KEY-----", "Private Key"),
            ('password = "supersecretpass123"', "Hardcoded Password"),
        ],
    )
    def test_pattern_detects(self, secret, label):
        matched = False
        for pattern, pattern_label in SECRET_PATTERNS:
            if pattern.search(secret):
                assert pattern_label == label
                matched = True
                break
        assert matched, f"Pattern for {label} did not match: {secret}"

    def test_safe_strings_not_matched(self):
        safe_strings = [
            "my_variable = 42",
            "api_url = 'https://api.example.com'",
            "password = ''",
            "sk-short",
            "AKIA_short",
        ]
        for safe in safe_strings:
            for pattern, label in SECRET_PATTERNS:
                assert not pattern.search(safe), f"False positive: {label} matched '{safe}'"


class TestAITracePattern:
    def test_detects_claude(self):
        assert AI_TRACE_PATTERN.search("Co-Authored-By: Claude <noreply@anthropic.com>")

    def test_detects_gpt(self):
        assert AI_TRACE_PATTERN.search("Co-Authored-By: GPT-4 <noreply@openai.com>")

    def test_detects_copilot(self):
        assert AI_TRACE_PATTERN.search("Co-Authored-By: Copilot")

    def test_no_false_positive(self):
        assert not AI_TRACE_PATTERN.search("Co-Authored-By: John Doe <john@example.com>")
        assert not AI_TRACE_PATTERN.search("Regular commit message")


class TestGitSecretScan:
    @pytest.mark.asyncio
    async def test_clean_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "clean.py").write_text("x = 42\n")
            result = await git_secret_scan(tmpdir)
            assert "No secrets found" in result

    @pytest.mark.asyncio
    async def test_detects_secret(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "config.py").write_text(
                'API_KEY = "sk-ant-abc123def456ghi789jkl012"\n'
            )
            result = await git_secret_scan(tmpdir)
            assert "issue(s) found" in result
            assert "Anthropic API Key" in result

    @pytest.mark.asyncio
    async def test_skips_binary_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "image.pyc").write_bytes(b"\x00\x01\x02")
            result = await git_secret_scan(tmpdir)
            assert "No secrets found" in result

    @pytest.mark.asyncio
    async def test_invalid_path(self):
        result = await git_secret_scan("/nonexistent/path")
        assert "Error" in result


class TestAuditLoggerDeepSanitize:
    """Перевірка рекурсивної санітизації."""

    def test_redacts_nested_token(self):
        from posipaka.security.audit import AuditLogger

        data = {"user": {"api_key": "sk-secret123", "name": "test"}}
        result = AuditLogger._sanitize_data(data)
        assert result["user"]["api_key"] == "***REDACTED***"
        assert result["user"]["name"] == "test"

    def test_redacts_credential_substring(self):
        from posipaka.security.audit import AuditLogger

        data = {"user_credential": "secret123"}
        result = AuditLogger._sanitize_data(data)
        assert result["user_credential"] == "***REDACTED***"

    def test_truncates_body(self):
        from posipaka.security.audit import AuditLogger

        data = {"body": "x" * 200}
        result = AuditLogger._sanitize_data(data)
        assert len(result["body"]) < 60
        assert result["body"].endswith("...")

    def test_handles_list(self):
        from posipaka.security.audit import AuditLogger

        data = {"items": [{"token": "secret"}, {"name": "safe"}]}
        result = AuditLogger._sanitize_data(data)
        assert result["items"][0]["token"] == "***REDACTED***"
        assert result["items"][1]["name"] == "safe"
