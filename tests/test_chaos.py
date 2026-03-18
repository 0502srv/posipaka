"""Chaos tests для graceful degradation."""

from __future__ import annotations

import pytest

from posipaka.core.degradation import DegradationManager, SystemMode, run_in_mode


class TestDegradationManager:
    def test_initial_mode_is_full(self):
        dm = DegradationManager()
        assert dm.mode == SystemMode.FULL

    def test_single_failure_degrades(self):
        dm = DegradationManager()
        dm.register_component("llm")
        dm.report_failure("llm", "timeout")
        assert dm.mode == SystemMode.DEGRADED

    def test_critical_failure_emergency(self):
        dm = DegradationManager()
        dm.register_component("disk")
        dm.report_failure("disk", "no space")
        assert dm.mode == SystemMode.EMERGENCY

    def test_multiple_failures_minimal(self):
        dm = DegradationManager()
        dm.register_component("llm")
        dm.register_component("sqlite")
        dm.report_failure("llm", "down")
        dm.report_failure("sqlite", "locked")
        assert dm.mode == SystemMode.MINIMAL

    def test_recovery_restores_mode(self):
        dm = DegradationManager()
        dm.register_component("llm")
        dm.report_failure("llm", "down")
        assert dm.mode == SystemMode.DEGRADED
        dm.report_recovery("llm")
        assert dm.mode == SystemMode.FULL

    def test_fallback_matrix(self):
        dm = DegradationManager()
        assert dm.get_fallback("llm") == "semantic_cache"
        assert dm.get_fallback("chromadb") == "tantivy_search"
        assert dm.get_fallback("unknown") is None

    def test_health_report(self):
        dm = DegradationManager()
        dm.register_component("llm")
        dm.register_component("sqlite")
        dm.report_failure("llm", "timeout")
        report = dm.check_system_health()
        assert report["mode"] == "degraded"
        assert report["components"]["llm"]["healthy"] is False
        assert report["components"]["sqlite"]["healthy"] is True

    @pytest.mark.asyncio
    async def test_run_in_mode_success(self):
        dm = DegradationManager()
        dm.register_component("test")

        async def primary():
            return "ok"

        result = await run_in_mode(dm, "test", primary)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_run_in_mode_fallback(self):
        dm = DegradationManager()
        dm.register_component("test")

        async def primary():
            raise ConnectionError("down")

        async def fallback():
            return "cached"

        result = await run_in_mode(dm, "test", primary, fallback)
        assert result == "cached"
        assert dm.mode == SystemMode.DEGRADED

    def test_mode_change_listener(self):
        dm = DegradationManager()
        dm.register_component("llm")
        changes: list[tuple] = []
        dm.on_mode_change(lambda old, new: changes.append((old.value, new.value)))
        dm.report_failure("llm", "down")
        assert len(changes) == 1
        assert changes[0] == ("full", "degraded")
