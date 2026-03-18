"""Тести для нових модулів: skill_sandbox, filesystem_policy, persona, heartbeat, privacy."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

# ─── SkillSandbox ──────────────────────────────────────────────────


class TestSkillSandbox:
    def test_safe_skill(self, tmp_path):
        from posipaka.security.skill_sandbox import SkillSandbox

        code = 'import json\nimport re\n\nasync def my_tool(): return "ok"\n'
        f = tmp_path / "tools.py"
        f.write_text(code)
        violations = SkillSandbox.validate_skill_source(f)
        assert violations == []

    def test_denied_import_os(self, tmp_path):
        from posipaka.security.skill_sandbox import SkillSandbox

        code = "import os\nos.system('rm -rf /')\n"
        f = tmp_path / "tools.py"
        f.write_text(code)
        violations = SkillSandbox.validate_skill_source(f)
        assert len(violations) >= 1
        assert "os" in violations[0]

    def test_denied_eval(self, tmp_path):
        from posipaka.security.skill_sandbox import SkillSandbox

        code = "x = eval('1+1')\n"
        f = tmp_path / "tools.py"
        f.write_text(code)
        violations = SkillSandbox.validate_skill_source(f)
        assert len(violations) >= 1
        assert "eval" in violations[0]

    def test_denied_subprocess(self, tmp_path):
        from posipaka.security.skill_sandbox import SkillSandbox

        code = "import subprocess\nsubprocess.run(['ls'])\n"
        f = tmp_path / "tools.py"
        f.write_text(code)
        violations = SkillSandbox.validate_skill_source(f)
        assert any("subprocess" in v for v in violations)

    def test_hash_and_lock(self, tmp_path):
        from posipaka.security.skill_sandbox import SkillSandbox

        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "tools.py").write_text("def foo(): pass\n")

        SkillSandbox.create_lock_file(skill_dir)
        assert SkillSandbox.verify_lock_file(skill_dir)

        # Modify file → lock mismatch
        (skill_dir / "tools.py").write_text("def bar(): pass\n")
        assert not SkillSandbox.verify_lock_file(skill_dir)


# ─── FilesystemPolicy ──────────────────────────────────────────────


class TestFilesystemPolicy:
    def test_allow_workspace(self):
        from posipaka.security.filesystem_policy import AccessDecision, FilesystemPolicy

        policy = FilesystemPolicy()
        result = policy.check_path("/tmp/test.txt", "read")
        assert result == AccessDecision.ALLOW

    def test_deny_ssh(self):
        from posipaka.security.filesystem_policy import AccessDecision, FilesystemPolicy

        policy = FilesystemPolicy()
        home = str(Path.home())
        result = policy.check_path(f"{home}/.ssh/id_rsa", "read")
        assert result == AccessDecision.DENY_HARD

    def test_deny_etc_shadow(self):
        from posipaka.security.filesystem_policy import AccessDecision, FilesystemPolicy

        policy = FilesystemPolicy()
        result = policy.check_path("/etc/shadow", "read")
        assert result == AccessDecision.DENY_HARD

    def test_write_requires_approval(self):
        from posipaka.security.filesystem_policy import AccessDecision, FilesystemPolicy

        policy = FilesystemPolicy()
        home = str(Path.home())
        result = policy.check_path(f"{home}/Documents/file.txt", "write")
        assert result == AccessDecision.REQUIRE_APPROVAL


# ─── PersonaManager ───────────────────────────────────────────────


class TestPersonaManager:
    def test_scan_builtin(self):
        from posipaka.personas.manager import PersonaManager

        pm = PersonaManager(
            data_dir=Path(tempfile.mkdtemp()),
            builtin_dir=Path(__file__).parent.parent.parent / "posipaka" / "personas" / "builtin",
        )
        personas = pm.scan()
        assert len(personas) >= 3  # trainer, dietitian, coach, tutor, senior_dev

    def test_activate_deactivate(self):
        from posipaka.personas.manager import PersonaManager

        pm = PersonaManager(
            data_dir=Path(tempfile.mkdtemp()),
            builtin_dir=Path(__file__).parent.parent.parent / "posipaka" / "personas" / "builtin",
        )
        pm.scan()
        names = [p["name"] for p in pm.list_personas()]
        if names:
            pm.activate(names[0])
            assert pm.active is not None
            pm.deactivate()
            assert pm.active is None

    def test_keyword_match(self):
        from posipaka.personas.manager import PersonaManager

        pm = PersonaManager(
            data_dir=Path(tempfile.mkdtemp()),
            builtin_dir=Path(__file__).parent.parent.parent / "posipaka" / "personas" / "builtin",
        )
        pm.scan()
        match = pm.match_keywords("хочу тренування")
        # May or may not find trainer depending on keywords
        # Just test that it doesn't crash
        assert match is None or match.name


# ─── SecretsRotation ──────────────────────────────────────────────


class TestSecretsRotation:
    def test_no_warnings_when_empty(self, tmp_path):
        from posipaka.security.rotation import SecretsRotationPolicy

        policy = SecretsRotationPolicy(tmp_path)
        assert policy.check_rotation_needed() == []

    def test_record_and_check(self, tmp_path):
        from posipaka.security.rotation import SecretsRotationPolicy

        policy = SecretsRotationPolicy(tmp_path)
        policy.record_rotation("LLM_API_KEY")
        # Just recorded → no warnings
        assert policy.check_rotation_needed() == []

    def test_report(self, tmp_path):
        from posipaka.security.rotation import SecretsRotationPolicy

        policy = SecretsRotationPolicy(tmp_path)
        report = policy.get_report()
        assert "актуальні" in report.lower() or "ротація" in report.lower()


# ─── PermissionMatrix ─────────────────────────────────────────────


class TestPermissionMatrix:
    def test_standard_profile(self):
        from posipaka.security.permission_matrix import (
            ResourcePermission,
            check_permission,
        )

        assert check_permission("standard", ResourcePermission.NET_INTERNET)
        assert check_permission("standard", ResourcePermission.SHELL_SAFE_COMMANDS)
        assert not check_permission("standard", ResourcePermission.SHELL_ARBITRARY)

    def test_minimal_profile(self):
        from posipaka.security.permission_matrix import (
            ResourcePermission,
            check_permission,
        )

        assert check_permission("minimal", ResourcePermission.FS_WRITE_TEMP)
        assert not check_permission("minimal", ResourcePermission.SHELL_SAFE_COMMANDS)

    def test_custom_override(self):
        from posipaka.security.permission_matrix import (
            ResourcePermission,
            check_permission,
        )

        # Standard disallows SHELL_ARBITRARY, but custom overrides
        assert check_permission(
            "standard",
            ResourcePermission.SHELL_ARBITRARY,
            custom_overrides={"shell.arbitrary": True},
        )


# ─── CostTracker ──────────────────────────────────────────────────


class TestCostTracker:
    @pytest.mark.asyncio
    async def test_record_and_report(self, tmp_path):
        from posipaka.core.cost_tracker import CostTracker

        tracker = CostTracker(tmp_path / "cost.db")
        await tracker.init()
        cost = await tracker.record("s1", "claude-sonnet-4-20250514", 1000, 500)
        assert cost > 0

        report = await tracker.get_cost_report()
        assert "Витрати" in report
        await tracker.close()

    @pytest.mark.asyncio
    async def test_daily_cost(self, tmp_path):
        from posipaka.core.cost_tracker import CostTracker

        tracker = CostTracker(tmp_path / "cost.db")
        await tracker.init()
        await tracker.record("s1", "gpt-4o-mini", 5000, 2000)
        daily = await tracker.get_daily_cost()
        assert daily > 0
        await tracker.close()


# ─── ComplexityManager ────────────────────────────────────────────────


class TestComplexityManager:
    def test_default_level(self):
        from posipaka.core.complexity import ComplexityManager

        cm = ComplexityManager()
        assert cm.get_level("user1").value == "standard"

    def test_set_level(self):
        from posipaka.core.complexity import ComplexityManager

        cm = ComplexityManager()
        assert cm.set_level("user1", "technical")
        assert cm.get_level("user1").value == "technical"

    def test_invalid_level(self):
        from posipaka.core.complexity import ComplexityManager

        cm = ComplexityManager()
        assert not cm.set_level("user1", "nonexistent")

    def test_system_prompt_addon(self):
        from posipaka.core.complexity import ComplexityManager

        cm = ComplexityManager()
        cm.set_level("user1", "eli5")
        addon = cm.get_system_prompt_addon("user1")
        assert "simplest" in addon.lower()

    def test_standard_no_addon(self):
        from posipaka.core.complexity import ComplexityManager

        cm = ComplexityManager()
        assert cm.get_system_prompt_addon("user1") == ""

    def test_available_levels(self):
        from posipaka.core.complexity import ComplexityManager

        levels = ComplexityManager.available_levels()
        assert "eli5" in levels
        assert "expert" in levels
        assert len(levels) == 4


# ─── TimezoneManager ─────────────────────────────────────────────────


class TestTimezoneManager:
    @pytest.mark.asyncio
    async def test_default_timezone(self):
        from posipaka.core.timezone_manager import UserTimezoneManager

        tm = UserTimezoneManager(default_tz="Europe/Kyiv")
        tz = await tm.get_timezone("user1")
        assert str(tz) == "Europe/Kyiv"

    @pytest.mark.asyncio
    async def test_set_timezone(self):
        from posipaka.core.timezone_manager import UserTimezoneManager

        tm = UserTimezoneManager()
        result = await tm.set_timezone("user1", "America/New_York")
        assert result  # returns tz name string
        tz = await tm.get_timezone("user1")
        assert "America/New_York" in str(tz)

    @pytest.mark.asyncio
    async def test_invalid_timezone(self):
        from posipaka.core.timezone_manager import UserTimezoneManager

        tm = UserTimezoneManager()
        with pytest.raises(ValueError):
            await tm.set_timezone("user1", "Invalid/Zone")

    @pytest.mark.asyncio
    async def test_get_user_now(self):
        from posipaka.core.timezone_manager import UserTimezoneManager

        tm = UserTimezoneManager(default_tz="UTC")
        now = await tm.get_user_now("user1")
        assert now.tzinfo is not None


# ─── IncidentManager ──────────────────────────────────────────────────


class TestIncidentManager:
    def test_default_rules(self):
        from posipaka.core.incident_response import IncidentManager

        im = IncidentManager()
        # IncidentManager has 5 default rules
        assert len(im._rules) >= 5

    @pytest.mark.asyncio
    async def test_check_metric_no_violation(self):
        from posipaka.core.incident_response import IncidentManager

        im = IncidentManager()
        incidents = await im.check_metric("error_rate", 0.01)
        assert len(incidents) == 0

    @pytest.mark.asyncio
    async def test_check_metric_violation(self):
        from posipaka.core.incident_response import IncidentManager

        im = IncidentManager()
        incidents = await im.check_metric("error_rate", 0.5)
        assert len(incidents) > 0
        assert incidents[0].severity == "critical"

    def test_get_runbook(self):
        from posipaka.core.incident_response import IncidentManager

        im = IncidentManager()
        rb = im.get_runbook("high_error_rate")
        assert rb is not None
        assert len(rb.steps) > 0


# ─── ModuleRegistry ──────────────────────────────────────────────────


class TestModuleRegistry:
    def test_register_and_list(self):
        from posipaka.core.module_registry import (
            BaseModule,
            ModuleInfo,
            ModuleRegistry,
            ModuleType,
        )

        class DummyModule(BaseModule):
            _info = ModuleInfo(
                name="dummy",
                module_type=ModuleType.CORE,
                version="1.0.0",
                description="Test module",
            )

            @property
            def info(self) -> ModuleInfo:
                return self._info

            async def initialize(self):
                pass

            async def shutdown(self):
                pass

            async def health_check(self) -> bool:
                return True

        reg = ModuleRegistry()
        mod = DummyModule()
        reg.register(mod)
        modules = reg.list_modules()
        assert len(modules) == 1
        assert modules[0].name == "dummy"

    def test_enable_disable(self):
        from posipaka.core.module_registry import (
            BaseModule,
            ModuleInfo,
            ModuleRegistry,
            ModuleType,
        )

        class DummyModule(BaseModule):
            _info = ModuleInfo(
                name="test_mod",
                module_type=ModuleType.INTEGRATION,
                version="1.0.0",
                description="Test",
            )

            @property
            def info(self) -> ModuleInfo:
                return self._info

            async def initialize(self):
                pass

            async def shutdown(self):
                pass

            async def health_check(self) -> bool:
                return True

        reg = ModuleRegistry()
        reg.register(DummyModule())
        assert reg.disable_module("test_mod")
        assert not reg.get("test_mod").enabled
        assert reg.enable_module("test_mod")
        assert reg.get("test_mod").enabled


# ─── ChaosEngine ─────────────────────────────────────────────────────


class TestChaosEngine:
    def test_disabled_by_default(self):
        from posipaka.core.chaos import ChaosEngine

        ce = ChaosEngine()
        assert not ce._active
        assert ce.should_inject("llm") is None

    def test_add_experiment(self):
        from posipaka.core.chaos import ChaosEngine, ChaosExperiment, FailureType

        ce = ChaosEngine()
        exp = ChaosExperiment(
            name="test_latency",
            failure_type=FailureType.LATENCY,
            target_component="llm",
            duration_seconds=60,
            probability=1.0,
        )
        ce.add_experiment(exp)
        report = ce.get_report()
        assert len(report["experiments"]) == 1


# ─── ExtensionAPI ────────────────────────────────────────────────────


class TestExtensionManager:
    def test_list_empty(self):
        from posipaka.core.extension_api import ExtensionManager

        em = ExtensionManager()
        assert em.list_extensions() == []


# ─── SkillVersioning ─────────────────────────────────────────────────


class TestSkillVersioning:
    def test_parse_version(self):
        from posipaka.skills.versioning import SkillVersion

        assert SkillVersion.parse("1.2.3") == (1, 2, 3)
        assert SkillVersion.parse("0.1.0") == (0, 1, 0)

    def test_compare(self):
        from posipaka.skills.versioning import SkillVersion

        assert SkillVersion.compare("1.0.0", "1.0.0") == 0
        assert SkillVersion.compare("1.1.0", "1.0.0") == 1
        assert SkillVersion.compare("0.9.0", "1.0.0") == -1

    def test_is_compatible(self):
        from posipaka.skills.versioning import SkillVersion

        assert SkillVersion.is_compatible("1.2.0", "1.0.0")
        assert not SkillVersion.is_compatible("2.0.0", "1.0.0")


# ─── JSON Logging ────────────────────────────────────────────────────


class TestJSONLogging:
    def test_setup_dev_mode(self):
        from posipaka.core.json_logging import setup_json_logging

        # Should not raise
        setup_json_logging(production=False)

    def test_get_trace_id(self):
        from posipaka.core.json_logging import get_trace_id

        tid = get_trace_id()
        assert isinstance(tid, str)
        assert len(tid) > 0


# ─── AuthManager ─────────────────────────────────────────────────────


class TestAuthManagerFixes:
    def test_concurrent_session_limit(self, tmp_path):

        from posipaka.web.auth import MAX_CONCURRENT_SESSIONS, AuthManager

        auth = AuthManager(tmp_path)
        auth.setup_password("test_password_1234")

        tokens = []
        for _i in range(MAX_CONCURRENT_SESSIONS + 2):
            tok = auth.create_session("1.2.3.4")
            tokens.append(tok)

        # Only MAX_CONCURRENT_SESSIONS should be valid
        valid_count = sum(1 for t in tokens if auth.validate_session(t))
        assert valid_count <= MAX_CONCURRENT_SESSIONS

    def test_cleanup_old_timestamps(self, tmp_path):
        import time

        from posipaka.web.auth import AuthManager

        auth = AuthManager(tmp_path)
        # Add old timestamps
        auth._failed_attempts["1.2.3.4"] = [
            time.time() - 10000,  # old
            time.time() - 10001,  # old
        ]
        lockout = auth.remaining_lockout_seconds("1.2.3.4")
        assert lockout == 0
        # Old timestamps should be cleaned up
        assert len(auth._failed_attempts["1.2.3.4"]) == 0


# ─── MemoryManager size limit ─────────────────────────────────────


class TestMemoryMdSizeLimit:
    @pytest.mark.asyncio
    async def test_update_truncates_large_content(self, tmp_path):
        from posipaka.memory.manager import MemoryManager

        mm = MemoryManager(
            sqlite_path=tmp_path / "mem.db",
            chroma_path=tmp_path / "chroma",
            memory_md_path=tmp_path / "MEMORY.md",
            chroma_enabled=False,
        )
        await mm.init()
        # Write content larger than MAX
        big = "x" * (mm.MAX_MEMORY_MD_BYTES + 1000)
        mm.update_memory_md(big)
        result = mm.get_memory_md()
        assert len(result.encode("utf-8")) <= mm.MAX_MEMORY_MD_BYTES
        await mm.close()

    def test_compact_deduplicates(self, tmp_path):
        from posipaka.memory.manager import MemoryManager

        mm = MemoryManager(
            sqlite_path=tmp_path / "mem.db",
            chroma_path=tmp_path / "chroma",
            memory_md_path=tmp_path / "MEMORY.md",
            chroma_enabled=False,
        )
        content = "# Facts\n" + "- Fact A\n" * 50 + "- Fact B\n"
        (tmp_path / "MEMORY.md").write_text(content, encoding="utf-8")
        result = mm.compact_memory_md()
        assert "стиснено" in result
        new_content = mm.get_memory_md()
        assert new_content.count("- Fact A") == 1


# ─── Observability ────────────────────────────────────────────────


class TestObservability:
    def test_counter(self):
        from posipaka.core.observability import MetricsRegistry

        reg = MetricsRegistry()
        reg.counter("test_total")
        reg.counter("test_total")
        data = reg.export_json()
        assert "counters" in data
        assert "test_total" in data["counters"]

    def test_gauge(self):
        from posipaka.core.observability import MetricsRegistry

        reg = MetricsRegistry()
        reg.gauge("test_gauge", 42.5)
        data = reg.export_json()
        assert "gauges" in data
        assert "test_gauge" in data["gauges"]

    def test_prometheus_export(self):
        from posipaka.core.observability import MetricsRegistry

        reg = MetricsRegistry()
        reg.counter("requests_total", {"method": "GET"})
        text = reg.export_prometheus()
        assert "requests_total" in text

    def test_reset(self):
        from posipaka.core.observability import MetricsRegistry

        reg = MetricsRegistry()
        reg.counter("x")
        reg.reset()
        data = reg.export_json()
        assert data["counters"] == {}
        assert data["gauges"] == {}


# ─── AutoUpdater ──────────────────────────────────────────────────


class TestAutoUpdater:
    def test_version_compare(self):
        from posipaka.core.auto_update import SemVer

        v1 = SemVer.parse("0.1.0")
        v2 = SemVer.parse("0.2.0")
        assert (v2.major, v2.minor) > (v1.major, v1.minor)

    def test_should_check_initially(self):
        from posipaka.core.auto_update import AutoUpdater

        u = AutoUpdater()
        assert u.should_check()


# ─── HEARTBEAT.md template ────────────────────────────────────────


class TestHeartbeatTemplate:
    def test_template_exists(self):
        from posipaka.config.defaults import HEARTBEAT_DEFAULT_CONTENT

        assert "Heartbeat" in HEARTBEAT_DEFAULT_CONTENT
        assert "перевіряти" in HEARTBEAT_DEFAULT_CONTENT
