"""Головний Agent клас — agentic loop."""

from __future__ import annotations

import asyncio
import re as _re
import time
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from posipaka.config.settings import Settings
from posipaka.core.agent_types import AgentStatus, PendingAction
from posipaka.core.approval_gate import ALL_TRIGGER_WORDS, ApprovalGate
from posipaka.core.cost_guard import CostGuard
from posipaka.core.hooks.manager import HookEvent, HookManager
from posipaka.core.llm import LLMClient
from posipaka.core.model_router import ModelRouter
from posipaka.core.prompt_builder import SystemPromptBuilder
from posipaka.core.semantic_cache import SemanticResponseCache
from posipaka.core.session import SessionManager
from posipaka.core.tools.compressor import ToolOutputCompressor
from posipaka.core.tools.registry import ToolRegistry
from posipaka.memory.manager import MemoryManager
from posipaka.security.audit import AuditLogger
from posipaka.security.injection import InjectionDetector


class Agent:
    """Головний агент Posipaka."""

    MAX_TOOL_LOOPS = 10
    MAX_CONTEXT_MESSAGES = 20  # Останні N повідомлень в контексті (економія токенів)
    MAX_CONTEXT_TOKENS = 12000  # Soft limit: обрізати історію якщо перевищує
    MAX_RESPONSE_LENGTH = 3000  # Hard limit: обрізати відповідь якщо довша

    def __init__(self, settings: Settings) -> None:
        # Apply runtime config (JSON) over env-based settings
        try:
            from posipaka.config.runtime_config import RuntimeConfig

            self.runtime_config = RuntimeConfig(settings.data_dir / "config.json")
            self.runtime_config.apply_to_settings(settings)
        except Exception as e:
            logger.debug(f"Runtime config: {e}")
            self.runtime_config = None
        self.settings = settings
        self.status = AgentStatus.INITIALIZING
        self.llm = LLMClient(settings)
        self.tools = ToolRegistry()
        self.memory: MemoryManager | None = None
        self.hooks = HookManager()
        self.audit = AuditLogger(settings.audit_log_path)
        self.injection_detector = InjectionDetector()
        self.sessions = SessionManager()
        self.cost_guard = CostGuard(
            daily_budget_usd=settings.cost.daily_budget_usd,
            per_request_max_usd=settings.cost.per_request_max_usd,
            per_session_max_usd=settings.cost.per_session_max_usd,
            warning_threshold=settings.cost.warning_threshold,
        )
        self._pending_approvals: dict[str, PendingAction] = {}
        self.model_router = self._init_model_router(settings)
        self.semantic_cache = SemanticResponseCache()
        self.output_compressor = ToolOutputCompressor()
        self.approval_gate = ApprovalGate(
            tools=self.tools,
            audit=self.audit,
            hooks=self.hooks,
            timeout_seconds=settings.security.approval_timeout_seconds,
        )
        self._pending_approvals = self.approval_gate.pending_approvals
        self.prompt_builder = SystemPromptBuilder(
            soul_md_path=settings.soul_md_path,
            user_md_path=settings.user_md_path,
            data_dir=settings.data_dir,
            timezone=settings.soul.timezone,
        )

        # Advanced modules (lazy init in _init_advanced_modules)
        self.degradation = None
        self.feature_flags = None
        self.permission_checker = None
        self.resource_monitor = None
        self.quality_monitor = None
        self.timezone_manager = None
        self.complexity_manager = None
        self.incident_manager = None
        self.module_registry = None

        # Initialized in initialize()
        self.orchestrator = None
        self.persona_manager = None
        self.cron_engine = None
        self.cron_history = None
        self.cron_executor = None
        self.scheduler = None
        self.heartbeat = None

    async def initialize(self) -> None:
        """Ініціалізація всіх підсистем.

        Phase 1 (CRITICAL): memory, tools, security — fail = don't start.
        Phase 2 (OPTIONAL): personas, cron, advanced — fail = log + continue.
        """
        self.settings.ensure_data_dir()

        # ── Phase 1: CRITICAL (failure here = agent won't start) ──
        # 1. Memory
        self.memory = MemoryManager(
            sqlite_path=self.settings.sqlite_db_path,
            chroma_path=self.settings.chroma_db_path,
            memory_md_path=self.settings.memory_md_path,
            short_term_limit=self.settings.memory.short_term_limit,
            chroma_enabled=self.settings.memory.chroma_enabled,
            tantivy_path=self.settings.data_dir / "tantivy",
            tantivy_enabled=True,
        )
        await self.memory.init()

        # 2. Load integrations + builtin skills
        self.tools.load_all_integrations()
        self._load_builtin_skills()

        # 3. Create default files
        self._ensure_default_files()

        # ── Phase 2: OPTIONAL (failure here = log warning, continue) ──
        # 4. Multi-agent orchestrator
        self._init_orchestrator()

        # 5. Persona manager
        self._init_personas()

        # 6. Cron engine (persistent)
        self._init_cron_engine()

        # 6.1 Attach remind skill to CronEngine
        self._attach_remind_to_cron()

        # 7. Advanced modules
        self._init_advanced_modules()

        # 8. Background update check
        self._schedule_update_check()

        # 9. Init tool router keyword cache (LLM-generated, async)
        await self._init_tool_router()

        self.status = AgentStatus.READY
        await self.hooks.emit(HookEvent.AGENT_START)
        self.audit.log("agent_start", {"version": "0.1.0"})
        logger.info("Agent initialized")

    def reload_settings(self) -> None:
        """Hot-reload: перечитати runtime config і переініціалізувати компоненти."""
        # 1. Перечитати runtime config
        if self.runtime_config:
            self.runtime_config._load()
            self.runtime_config.apply_to_settings(self.settings)

        # 2. Переініціалізувати LLM клієнт
        self.llm.reinitialize()

        # 3. Оновити CostGuard ліміти
        self.cost_guard.daily_budget = self.settings.cost.daily_budget_usd
        self.cost_guard.per_request_max = self.settings.cost.per_request_max_usd
        self.cost_guard.per_session_max = self.settings.cost.per_session_max_usd

        # 4. Переініціалізувати ModelRouter
        self.model_router = self._init_model_router(self.settings)

        self.audit.log("settings_hot_reloaded", {})
        logger.info("Settings hot-reloaded successfully")

    def _load_builtin_skills(self) -> None:
        """Завантажити builtin skills (summarize, translate, remind, research)."""
        from pathlib import Path

        builtin_dir = Path(__file__).parent.parent / "skills" / "builtin"
        if not builtin_dir.exists():
            return
        for skill_dir in builtin_dir.iterdir():
            if skill_dir.is_dir() and (skill_dir / "tools.py").exists():
                self.tools.load_skill_dir(skill_dir)

        # Load workspace skills
        user_skills = self.settings.data_dir / "skills"
        if user_skills.exists():
            for skill_dir in user_skills.iterdir():
                if skill_dir.is_dir() and (skill_dir / "tools.py").exists():
                    # Validate workspace skills
                    try:
                        from posipaka.security.skill_sandbox import SkillSandbox

                        violations = SkillSandbox.validate_skill_source(skill_dir / "tools.py")
                        if violations:
                            logger.warning(f"Skill '{skill_dir.name}' blocked: {violations}")
                            continue
                    except Exception:
                        pass
                    self.tools.load_skill_dir(skill_dir)

    def _init_orchestrator(self) -> None:
        """Ініціалізація multi-agent orchestrator."""
        try:
            from posipaka.core.agents.analysis_agent import AnalysisAgent
            from posipaka.core.agents.calendar_agent import CalendarAgent
            from posipaka.core.agents.code_agent import CodeAgent
            from posipaka.core.agents.devops_agent import DevOpsAgent
            from posipaka.core.agents.notification_agent import NotificationAgent
            from posipaka.core.agents.orchestrator import AgentOrchestrator
            from posipaka.core.agents.research_agent import ResearchAgent
            from posipaka.core.agents.security_agent import SecurityAgent
            from posipaka.core.agents.web_agent import WebAgent
            from posipaka.core.agents.writer_agent import WriterAgent

            self.orchestrator = AgentOrchestrator()
            self.orchestrator.register_agent(ResearchAgent())
            self.orchestrator.register_agent(CodeAgent())
            self.orchestrator.register_agent(CalendarAgent())
            self.orchestrator.register_agent(DevOpsAgent())
            self.orchestrator.register_agent(AnalysisAgent())
            self.orchestrator.register_agent(SecurityAgent())
            self.orchestrator.register_agent(WriterAgent())
            self.orchestrator.register_agent(NotificationAgent())
            self.orchestrator.register_agent(WebAgent())
            count = len(self.orchestrator._agents)
            logger.debug(f"Orchestrator: {count} agents registered")
        except Exception as e:
            logger.warning(f"Orchestrator init error: {e}")

    @staticmethod
    def _init_model_router(settings: Any) -> ModelRouter:
        """Ініціалізація ModelRouter з файлу або дефолтів."""
        import json

        config_path = settings.data_dir / "model_router.json"
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text("utf-8"))
                from posipaka.core.model_router import ModelRouterConfig

                config = ModelRouterConfig.from_dict(data)
                logger.debug(f"ModelRouter loaded from config: mode={config.mode}")
                return ModelRouter(config=config)
            except Exception as e:
                logger.warning(f"ModelRouter config error: {e}")

        return ModelRouter(
            default_model=settings.llm.model,
            fast_model=getattr(
                settings.llm,
                "fast_model",
                settings.llm.fallback_model,
            ),
            complex_model=settings.llm.model,
        )

    def _init_personas(self) -> None:
        """Ініціалізація persona manager."""
        try:
            from posipaka.personas.manager import PersonaManager

            self.persona_manager = PersonaManager(self.settings.data_dir)
            personas = self.persona_manager.scan()
            logger.debug(f"Personas: {len(personas)} loaded")
        except Exception as e:
            logger.warning(f"PersonaManager init error: {e}")

    def _init_cron_engine(self) -> None:
        """Ініціалізація persistent cron engine + executor + history + scheduler."""
        try:
            from posipaka.core.cron_engine import CronEngine

            cron_dir = self.settings.data_dir / "cron"
            self.cron_engine = CronEngine(cron_dir)
            self.cron_engine.init()
            logger.debug(f"CronEngine: {len(self.cron_engine.list_jobs())} jobs loaded")
        except Exception as e:
            logger.warning(f"CronEngine init error: {e}")

        # History + DLQ (SQLite)
        try:
            from posipaka.core.cron_history import CronHistory

            db_path = self.settings.data_dir / "cron_history.db"
            self.cron_history = CronHistory(db_path)
            self.cron_history.init()
        except Exception as e:
            self.cron_history = None
            logger.warning(f"CronHistory init error: {e}")

        # Scheduler (APScheduler)
        try:
            from posipaka.core.scheduler import PosipakScheduler

            self.scheduler = PosipakScheduler()
        except Exception as e:
            self.scheduler = None
            logger.warning(f"Scheduler init error: {e}")

        # Executor — wired to all infrastructure.
        # gateway_provider resolves lazily because gateway starts after agent init.
        try:
            from posipaka.core.cron_executor import CronExecutor

            self.cron_executor = CronExecutor(
                cron_engine=self.cron_engine,
                gateway_provider=lambda: getattr(self, "gateway", None),
                history=self.cron_history,
                workflow_engine=getattr(self, "workflow_engine", None),
                hooks=self.hooks,
                degradation=getattr(self, "degradation", None),
                cost_guard=self.cost_guard,
                slo_monitor=getattr(self, "slo_monitor", None),
            )
        except Exception as e:
            self.cron_executor = None
            logger.warning(f"CronExecutor init error: {e}")

    def _attach_remind_to_cron(self) -> None:
        """Підключити remind skill до CronEngine агента.

        Skills завантажуються через importlib.util.spec_from_file_location()
        як окремий модуль (skill_remind), тому його globals відрізняються від
        posipaka.skills.builtin.remind.tools. Підключаємо через обидва шляхи.
        """
        try:
            # 1. Attach via handler's actual module (skill_remind)
            tool_def = self.tools.get("set_reminder")
            if tool_def and tool_def.handler:
                handler_module = __import__("sys").modules.get(tool_def.handler.__module__)
                if handler_module and hasattr(handler_module, "_attach_to_agent"):
                    handler_module._attach_to_agent(self)
                    logger.debug(
                        f"Remind skill attached via handler module: {tool_def.handler.__module__}"
                    )

            # 2. Also attach via package import (for direct imports elsewhere)
            from posipaka.skills.builtin.remind.tools import _attach_to_agent

            _attach_to_agent(self)
            logger.debug("Remind skill also attached via package import")
        except Exception as e:
            logger.warning(f"Failed to attach remind skill to CronEngine: {e}")

    async def _init_tool_router(self) -> None:
        """Initialize tool router with LLM-generated keyword cache."""
        try:
            from posipaka.core.tool_router import init_router

            all_schemas = self.tools.get_schemas(self.settings.llm.provider)
            await init_router(all_schemas, self.llm)
        except Exception as e:
            logger.debug(f"Tool router init: {e}")

    def _schedule_update_check(self) -> None:
        """Фонова перевірка оновлень при старті (не блокує).

        Якщо знайдено нову версію — надсилає повідомлення
        через активні канали (Telegram тощо).
        """
        try:
            from posipaka.core.auto_update import AutoUpdater

            updater = AutoUpdater(
                data_dir=self.settings.data_dir,
                audit_logger=self.audit,
            )
            if not updater.should_check():
                return

            async def _check() -> None:
                try:
                    info = await updater.check_for_updates()
                    if not info.update_available:
                        return
                    msg = (
                        f"Доступне оновлення Posipaka: "
                        f"v{info.current_version} → v{info.latest_version}\n"
                        f"Надішліть /update для оновлення."
                    )
                    logger.info(msg)
                    # Надіслати адміну через gateway (Telegram тощо)
                    if self.gateway:
                        admin_id = getattr(self.settings, "admin_user_id", "")
                        if admin_id:
                            await self.gateway.broadcast(admin_id, msg)
                except Exception as e:
                    logger.debug(f"Background update check failed: {e}")

            asyncio.create_task(_check())
        except Exception as e:
            logger.debug(f"Update check init: {e}")

    def _init_advanced_modules(self) -> None:
        """Ініціалізація advanced модулів."""
        # DegradationManager
        try:
            from posipaka.core.degradation import DegradationManager

            self.degradation = DegradationManager()
            for component in ("llm", "sqlite", "chromadb", "tantivy", "network", "disk"):
                self.degradation.register_component(component)
            logger.debug("DegradationManager initialized")
        except Exception as e:
            logger.debug(f"DegradationManager not available: {e}")

        # FeatureFlagManager
        try:
            from posipaka.core.feature_flags import FeatureFlagManager

            flags_db = self.settings.data_dir / "feature_flags.db"
            self.feature_flags = FeatureFlagManager(flags_db)
            logger.debug("FeatureFlagManager initialized")
        except Exception as e:
            logger.debug(f"FeatureFlagManager not available: {e}")

        # PermissionChecker (інтеграція з ToolRegistry)
        try:
            from posipaka.core.permission_checker import PermissionChecker

            self.permission_checker = PermissionChecker()
            self.tools.set_permission_checker(self.permission_checker)
            logger.debug("PermissionChecker initialized and linked to ToolRegistry")
        except Exception as e:
            logger.debug(f"PermissionChecker not available: {e}")

        # ResourceMonitor
        try:
            from posipaka.core.resource_monitor import ResourceMonitor

            self.resource_monitor = ResourceMonitor()
            logger.debug("ResourceMonitor initialized")
        except Exception as e:
            logger.debug(f"ResourceMonitor not available: {e}")

        # QualityMonitor
        try:
            from posipaka.core.quality import QualityMonitor

            self.quality_monitor = QualityMonitor()
            logger.debug("QualityMonitor initialized")
        except Exception as e:
            logger.debug(f"QualityMonitor not available: {e}")

        # UserTimezoneManager
        try:
            from posipaka.core.timezone_manager import UserTimezoneManager

            self.timezone_manager = UserTimezoneManager(default_tz=self.settings.soul.timezone)
            logger.debug("UserTimezoneManager initialized")
        except Exception as e:
            logger.debug(f"UserTimezoneManager not available: {e}")

        # ComplexityManager
        try:
            from posipaka.core.complexity import ComplexityManager

            self.complexity_manager = ComplexityManager()
            logger.debug("ComplexityManager initialized")
        except Exception as e:
            logger.debug(f"ComplexityManager not available: {e}")

        # IncidentManager
        try:
            from posipaka.core.incident_response import IncidentManager

            self.incident_manager = IncidentManager(self.settings.data_dir)
            logger.debug("IncidentManager initialized")
        except Exception as e:
            logger.debug(f"IncidentManager not available: {e}")

        # ModuleRegistry
        try:
            from posipaka.core.module_registry import ModuleRegistry

            self.module_registry = ModuleRegistry()
            logger.debug("ModuleRegistry initialized")
        except Exception as e:
            logger.debug(f"ModuleRegistry not available: {e}")

        # BackupManager з автоматичним розкладом
        try:
            from posipaka.utils.backup import BackupManager

            self.backup_manager = BackupManager(self.settings.data_dir)
            # Створити бекап при старті, якщо останній старше 24 годин
            self._maybe_auto_backup()
            logger.debug("BackupManager initialized")
        except Exception as e:
            logger.debug(f"BackupManager not available: {e}")

    def _maybe_auto_backup(self) -> None:
        """Автоматичний бекап при старті, якщо останній старше 24 годин."""
        import time as _time

        try:
            backup_mgr = getattr(self, "backup_manager", None)
            if not backup_mgr:
                return
            backups = backup_mgr.list_backups()
            if backups:
                from datetime import datetime

                last_created = datetime.fromisoformat(backups[0]["created"])
                age_hours = (_time.time() - last_created.timestamp()) / 3600
                if age_hours < 24:
                    return  # бекап свіжий — пропускаємо
            path = backup_mgr.create_backup()
            backup_mgr.cleanup_old_backups(keep=5)
            self.audit.log("auto_backup", {"path": str(path)})
        except Exception as e:
            logger.error(f"Auto-backup failed: {e}")

    def _ensure_default_files(self) -> None:
        """Створити SOUL.md, USER.md, MEMORY.md, MEMORY-CORE.md, MEMORY-DYNAMIC.md."""
        from posipaka.config.defaults import (
            HEARTBEAT_DEFAULT_CONTENT,
            MEMORY_CORE_DEFAULT_CONTENT,
            MEMORY_DEFAULT_CONTENT,
            MEMORY_DYNAMIC_DEFAULT_CONTENT,
            SOUL_DEFAULT_CONTENT,
            USER_DEFAULT_CONTENT,
        )

        data_dir = self.settings.data_dir
        heartbeat_path = data_dir / "HEARTBEAT.md"
        core_path = data_dir / "MEMORY-CORE.md"
        dynamic_path = data_dir / "MEMORY-DYNAMIC.md"

        for path, content in [
            (self.settings.soul_md_path, SOUL_DEFAULT_CONTENT),
            (self.settings.user_md_path, USER_DEFAULT_CONTENT),
            (self.settings.memory_md_path, MEMORY_DEFAULT_CONTENT),
            (heartbeat_path, HEARTBEAT_DEFAULT_CONTENT),
            (core_path, MEMORY_CORE_DEFAULT_CONTENT),
            (dynamic_path, MEMORY_DYNAMIC_DEFAULT_CONTENT),
        ]:
            if not path.exists():
                path.write_text(content, encoding="utf-8")

    async def _cron_agent_fn(
        self,
        message: str,
        user_id: str,
        session_mode: str = "isolated",
        session_name: str = "",
        session_id: str | None = None,
        model: str | None = None,
    ) -> str:
        """Wrapper для виконання cron job через агент."""
        sid = session_id or f"cron:{user_id}"
        result_parts = []
        async for chunk in self.handle_message(message, sid, context="cron_job"):
            result_parts.append(chunk)
        return "".join(result_parts)

    async def handle_message(
        self, content: str, session_id: str, context: str = "direct_message"
    ) -> AsyncIterator[str]:
        """Головна точка входу для повідомлень."""
        msg_start_time = time.time()
        self.status = AgentStatus.PROCESSING
        try:
            # Audit
            self.audit.log(
                "message_received",
                {
                    "session_id": session_id,
                    "content": content,
                },
            )
            await self.hooks.emit(
                HookEvent.MESSAGE_RECEIVED,
                {
                    "content": content,
                    "session_id": session_id,
                },
            )

            # Input length check
            max_len = self.settings.security.max_input_length
            if len(content) > max_len:
                yield (
                    f"Повідомлення занадто довге: {len(content)} символів "
                    f"(максимум {max_len}). Спробуйте коротше."
                )
                return

            # Injection check
            risk = self.injection_detector.check(content, context)
            if risk.is_dangerous:
                self.audit.log(
                    "injection_detected",
                    {
                        "score": risk.score,
                        "reasons": risk.reasons,
                    },
                )
                yield (
                    "Виявлено потенційно небезпечний вміст у повідомленні. "
                    "Запит відхилено з міркувань безпеки."
                )
                return

            # Cleanup expired approvals
            await self.approval_gate.cleanup_expired()

            # Check pending approvals
            if content.lower().strip() in ALL_TRIGGER_WORDS:
                result = await self.approval_gate.process_response(content, session_id)
                if result:
                    yield result
                    return

            # Semantic cache check — повернути cached відповідь якщо є
            cached = await self.semantic_cache.check(content, session_id)
            if cached:
                self.audit.log("cache_hit", {"content": content})
                yield cached
                return

            # Save to memory
            if self.memory is None:
                raise RuntimeError("Agent.initialize() must be called before handle_message")
            await self.memory.add(session_id, {"role": "user", "content": content})

            # Build system prompt (з persona addon якщо активна)
            system_prompt = await self.prompt_builder.build(
                session_id, memory=self.memory, tools=self.tools
            )
            if self.persona_manager and self.persona_manager.active:
                system_prompt += "\n\n" + self.persona_manager.get_system_prompt_addon()
            # Add complexity level addon
            if self.complexity_manager:
                addon = self.complexity_manager.get_system_prompt_addon(session_id)
                if addon:
                    system_prompt += "\n\n" + addon
            # Add timezone info
            if self.timezone_manager:
                tz_info = await self.timezone_manager.format_for_system_prompt(session_id)
                if tz_info:
                    system_prompt += "\n\n" + tz_info

            # Get recent history (deduplicate consecutive same-role messages)
            # Trim to MAX_CONTEXT_TOKENS to avoid wasting tokens on old messages
            recent = await self.memory.get_recent(session_id, self.MAX_CONTEXT_MESSAGES)
            # Token budget: trim from oldest until under limit
            total_chars = sum(len(m.get("content", "")) for m in recent)
            estimated_tokens = total_chars // 3  # ~3 chars per token for UA/mixed
            while estimated_tokens > self.MAX_CONTEXT_TOKENS and len(recent) > 2:
                removed = recent.pop(0)
                estimated_tokens -= len(removed.get("content", "")) // 3

            messages: list[dict[str, str]] = []
            for m in recent:
                role, content_text = m["role"], m["content"]
                if messages and messages[-1]["role"] == role:
                    messages[-1]["content"] += "\n" + content_text
                else:
                    messages.append({"role": role, "content": content_text})
            # Ensure first message is user (required by most LLMs)
            if messages and messages[0]["role"] != "user":
                messages = messages[1:]

            # Get tool schemas + smart routing
            all_schemas = self.tools.get_schemas(self.settings.llm.provider)

            from posipaka.core.tool_router import route_tools

            route = route_tools(content, all_schemas, self.settings.llm.provider)
            tool_schemas = route.tools
            tool_choice = route.tool_choice
            logger.debug(
                f"ToolRouter: {len(tool_schemas)} tools, "
                f"choice={tool_choice}, confident={route.confident}, "
                f"names={[s.get('function', {}).get('name') or s.get('name', '') for s in tool_schemas[:5]]}"
            )

            # Model routing — вибрати оптимальну модель + settings
            selected_profile = self.model_router.select_profile(
                content,
                tools_count=len(tool_schemas),
            )
            selected_model = selected_profile.model

            # Agentic loop
            _last_tool_error = False
            for _iteration in range(self.MAX_TOOL_LOOPS):
                # CostGuard check
                estimated_tokens = sum(
                    self.cost_guard.estimate_tokens(
                        m.get("content", ""),
                        selected_model,
                    )
                    for m in messages
                ) + self.cost_guard.estimate_tokens(
                    system_prompt,
                    selected_model,
                )
                allowed, reason = self.cost_guard.check_before_call(
                    model=selected_model,
                    estimated_input_tokens=estimated_tokens,
                    session_id=session_id,
                )
                if not allowed:
                    yield reason
                    return

                # LLM call with selected model + degradation handling
                # iter 0: pass filtered tools with tool_choice hint
                # iter 1+: if confident routing AND last tool succeeded — no tools (force text)
                #          if last tool had error — keep tools so model can retry
                if _iteration == 0:
                    iter_tools = tool_schemas if tool_schemas else None
                    iter_choice = tool_choice
                elif route.confident and _iteration >= 1 and not _last_tool_error:
                    iter_tools = None
                    iter_choice = None
                else:
                    iter_tools = tool_schemas if tool_schemas else None
                    iter_choice = None

                try:
                    logger.debug(
                        f"LLM call: model={selected_model}, "
                        f"tools={len(iter_tools) if iter_tools else 0}, "
                        f"tool_choice={iter_choice}, iter={_iteration}"
                    )
                    response = await self.llm.complete(
                        system=system_prompt,
                        messages=messages,
                        tools=iter_tools,
                        model=selected_model,
                        tool_choice=iter_choice,
                    )
                    logger.debug(
                        f"LLM response: stop={response.get('stop_reason')}, "
                        f"tool_use={len(response.get('tool_use', []))}, "
                        f"content_len={len(response.get('content', ''))}"
                    )
                    if self.degradation:
                        self.degradation.report_recovery("llm")
                except Exception as e:
                    if isinstance(e, (KeyboardInterrupt, SystemExit)):
                        raise
                    logger.error(f"LLM call failed: {e}")
                    if self.degradation:
                        self.degradation.report_failure("llm", str(e))
                        # Try semantic cache as fallback
                        cached = await self.semantic_cache.check(content, session_id)
                        if cached:
                            yield cached
                            return
                    yield "AI-модель тимчасово недоступна. Спробуйте пізніше."
                    return

                # Record cost
                self.cost_guard.record(
                    model=self.settings.llm.model,
                    input_tokens=response["usage"]["input_tokens"],
                    output_tokens=response["usage"]["output_tokens"],
                    session_id=session_id,
                )

                # If text response — done (or retry if model ignored tool_choice)
                if response["stop_reason"] == "end_turn" or not response["tool_use"]:
                    text = response["content"]

                    # Weak model retry: if tool_choice was forced but model
                    # returned text instead of tool call — retry once with
                    # explicit instruction in user message
                    if (
                        _iteration == 0
                        and route.confident
                        and iter_choice
                        and isinstance(iter_choice, dict)
                        and text
                    ):
                        forced_tool = iter_choice.get("function", {}).get("name", "")
                        if forced_tool:
                            logger.debug(
                                f"Weak model retry: model ignored tool_choice={forced_tool}, "
                                f"injecting instruction"
                            )
                            messages.append({"role": "assistant", "content": text})
                            messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        f"Ти ОБОВ'ЯЗКОВО повинен викликати функцію {forced_tool}. "
                                        f"Не відповідай текстом — виклич інструмент."
                                    ),
                                }
                            )
                            # Restore tools for retry
                            iter_tools = tool_schemas if tool_schemas else None
                            iter_choice = tool_choice
                            continue  # retry this iteration

                    if text:
                        # Hard limit: обрізати занадто довгі відповіді
                        text = self._truncate_response(text, self.MAX_RESPONSE_LENGTH)
                        response_time = time.time() - msg_start_time
                        await self.memory.add(session_id, {"role": "assistant", "content": text})
                        await self.memory.maybe_extract_facts(session_id, content)
                        # Cache response for similar future queries
                        await self.semantic_cache.store(content, text, session_id)
                        self.audit.log(
                            "response_sent",
                            {
                                "content": text,
                                "model": selected_model,
                                "tool_calls": _iteration,
                            },
                        )
                        # Quality scoring
                        if self.quality_monitor:
                            import contextlib

                            with contextlib.suppress(Exception):
                                self.quality_monitor.score_response(
                                    query=content,
                                    response=text,
                                    tool_calls=_iteration,
                                    response_time=response_time,
                                )
                        yield text
                    return

                # Handle tool calls
                for tool_call in response["tool_use"]:
                    tool_name = tool_call["name"]
                    tool_input = tool_call["input"]
                    tool_id = tool_call["id"]

                    self.audit.log(
                        "tool_call",
                        {
                            "tool": tool_name,
                            "input": tool_input,
                        },
                    )
                    await self.hooks.emit(
                        HookEvent.BEFORE_TOOL_CALL,
                        {
                            "tool": tool_name,
                            "input": tool_input,
                        },
                    )

                    # Check if approval needed
                    if self.approval_gate.requires_approval(tool_name):
                        action = self.approval_gate.request(
                            tool_name,
                            tool_input,
                            session_id,
                        )
                        await self.hooks.emit(
                            HookEvent.APPROVAL_REQUESTED,
                            {"action": action},
                        )
                        yield (
                            f"Потрібне підтвердження:\n"
                            f"{action.description}\n\n"
                            f"Відповідайте 'так' або 'ні'"
                        )
                        return

                    # Execute tool
                    try:
                        result = await self.tools.execute(tool_name, tool_input)
                        result_str = str(result)
                        # Compress large tool outputs to save tokens
                        result_str = self.output_compressor.compress(tool_name, result_str)
                        _last_tool_error = "Error" in result_str
                    except Exception as e:
                        result_str = f"Error: {e}"
                        _last_tool_error = True
                        await self.hooks.emit(
                            HookEvent.TOOL_ERROR,
                            {
                                "tool": tool_name,
                                "error": str(e),
                            },
                        )

                    self.audit.log(
                        "tool_result",
                        {
                            "tool": tool_name,
                            "status": "success" if "Error" not in result_str else "error",
                        },
                    )
                    await self.hooks.emit(
                        HookEvent.AFTER_TOOL_CALL,
                        {
                            "tool": tool_name,
                            "result": result_str[:100],
                        },
                    )

                    # Add tool result to messages for next iteration
                    if self.settings.llm.provider == "anthropic":
                        messages.append(
                            {
                                "role": "assistant",
                                "content": response["content"] if response["content"] else "",
                            }
                        )
                        # For Anthropic, tool results go as user message with tool_result block
                        messages.append(
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": tool_id,
                                        "content": result_str,
                                    }
                                ],
                            }
                        )
                    else:
                        # OpenAI/Mistral format: assistant with tool_calls + tool result
                        import json

                        messages.append(
                            {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "id": tool_id,
                                        "type": "function",
                                        "function": {
                                            "name": tool_name,
                                            "arguments": json.dumps(tool_input),
                                        },
                                    }
                                ],
                                "content": response["content"] or "",
                            }
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "content": result_str,
                            }
                        )

            yield "Досягнуто максимальну кількість ітерацій. Спробуйте спростити запит."

        except Exception as e:
            logger.error(f"Agent error: {e}")
            self.audit.log("agent_error", {"error": str(e)})
            await self.hooks.emit(HookEvent.AGENT_ERROR, {"error": str(e)})
            yield f"Виникла помилка: {e}"
        finally:
            self.status = AgentStatus.READY

    @staticmethod
    def _truncate_response(text: str, max_length: int) -> str:
        """Страховка: обрізати відповідь якщо модель проігнорувала промпт.

        Дедуплікує абзаци + hard truncate по межі абзацу.
        Основний контроль довжини — через max_tokens та system prompt.
        """
        if len(text) <= max_length:
            # Навіть короткий текст: дедуплікувати абзаци
            paragraphs = text.split("\n\n")
            seen: set[str] = set()
            unique: list[str] = []
            for p in paragraphs:
                norm = p.strip()
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                unique.append(p)
            return "\n\n".join(unique).rstrip()

        # Дедуплікація абзаців
        paragraphs = text.split("\n\n")
        seen: set[str] = set()
        unique: list[str] = []
        for p in paragraphs:
            norm = p.strip()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            unique.append(p)
        text = "\n\n".join(unique).rstrip()

        if len(text) <= max_length:
            return text

        # Hard truncate: обрізати до останнього повного абзацу
        truncated = text[:max_length]
        last_para = truncated.rfind("\n\n")
        if last_para > max_length // 2:
            truncated = truncated[:last_para]
        else:
            last_nl = truncated.rfind("\n")
            if last_nl > max_length // 2:
                truncated = truncated[:last_nl]

        return truncated.rstrip()

    async def handle_command(self, command: str, args: str, user_id: str) -> str:
        """Обробка /команд."""
        if command == "status":
            return self._format_status()
        if command == "reset":
            session = self.sessions.get_or_create(user_id, "cli")
            if self.memory:
                await self.memory.clear_session(session.id)
            return "Сесію скинуто."
        if command == "cost":
            return self.cost_guard.get_daily_report()
        if command == "memory":
            if self.memory:
                return self.memory.get_memory_md() or "Пам'ять порожня."
            return "Memory not initialized."
        if command == "skills":
            tools = self.tools.list_tools()
            if not tools:
                return "Немає зареєстрованих інструментів."
            return "\n".join(
                f"{'✅' if t['enabled'] else '❌'} {t['name']} — {t['description']}" for t in tools
            )
        if command == "persona":
            if not self.persona_manager:
                return "Персони не ініціалізовані."
            if not args:
                personas = self.persona_manager.list_personas()
                if not personas:
                    return "Немає доступних персон."
                lines = ["Доступні персони:"]
                for p in personas:
                    active = " (активна)" if p["active"] else ""
                    lines.append(f"  {p['display_name']}{active} — {p['description']}")
                lines.append("\n/persona <name> — активувати\n/persona off — вимкнути")
                return "\n".join(lines)
            if args.strip() == "off":
                self.persona_manager.deactivate()
                return "Повернення до звичайного режиму."
            persona = self.persona_manager.activate(args.strip())
            if persona:
                return f"Персона '{persona.display_name}' активована."
            return f"Персона '{args}' не знайдена."
        if command == "heartbeat":
            if not self.heartbeat:
                return "Heartbeat не ініціалізований."
            return self.heartbeat.get_status()
        if command == "cron":
            if not self.cron_engine:
                return "CronEngine не ініціалізований."
            sub = (args or "").strip().split(maxsplit=1)
            subcmd = sub[0] if sub else "list"
            subargs = sub[1] if len(sub) > 1 else ""

            if subcmd == "runs":
                if not self.cron_history:
                    return "CronHistory не ініціалізований."
                return self.cron_history.format_runs(subargs or None)

            if subcmd == "run" and subargs:
                if not self.cron_executor:
                    return "CronExecutor не ініціалізований."
                job = self.cron_engine.get(subargs)
                if not job:
                    return f"Job '{subargs}' не знайдено."
                result = await self.cron_executor.execute_job(
                    job,
                    agent_fn=self._cron_agent_fn,
                )
                return result or "Job виконано (без результату)."

            if subcmd == "stats" and subargs:
                if not self.cron_history:
                    return "CronHistory не ініціалізований."
                job = self.cron_engine.get(subargs)
                if not job:
                    return f"Job '{subargs}' не знайдено."
                stats = self.cron_history.get_stats(job.id)
                return (
                    f"Статистика '{job.name}':\n"
                    f"  Всього: {stats['total']}\n"
                    f"  Успішно: {stats['success']}\n"
                    f"  Помилки: {stats['failed']}\n"
                    f"  Сер. час: {stats['avg_duration']}s"
                )

            if subcmd == "dlq":
                if not self.cron_history:
                    return "CronHistory не ініціалізований."
                return self.cron_history.format_dlq()

            if subcmd == "retry" and subargs:
                if not self.cron_history or not self.cron_executor:
                    return "CronHistory/Executor не ініціалізований."
                try:
                    dlq_id = int(subargs)
                except ValueError:
                    return "Вкажіть DLQ ID (число)."
                dlq_entries = self.cron_history.get_dlq()
                entry = next((e for e in dlq_entries if e["id"] == dlq_id), None)
                if not entry:
                    return f"DLQ #{dlq_id} не знайдено."
                job = self.cron_engine.get(entry["job_id"])
                if not job:
                    return f"Job '{entry['job_name']}' більше не існує."
                self.cron_history.resolve_dlq(dlq_id, resolved_by="manual_retry")
                result = await self.cron_executor.execute_job(
                    job,
                    agent_fn=self._cron_agent_fn,
                )
                return result or "Retry виконано (без результату)."

            # Default: list
            jobs = self.cron_engine.list_jobs()
            if not jobs:
                return "Немає запланованих завдань."
            lines = ["Заплановані завдання:"]
            dlq_count = self.cron_history.dlq_count() if self.cron_history else 0
            if dlq_count:
                lines.append(f"  ⚠️ DLQ: {dlq_count} pending")
            for j in jobs:
                status = "✅" if j["enabled"] else "❌"
                target = f" → {j['target']}" if j.get("delivery") != "none" else ""
                lines.append(f"  {status} {j['name']} [{j['type']}] — {j['schedule']}{target}")
            return "\n".join(lines)
        if command == "compact":
            if self.memory:
                if self.memory.check_memory_md_size():
                    return self.memory.compact_memory_md()
                return "MEMORY.md не потребує стиснення."
            return "Memory не ініціалізовано."
        if command == "update":
            try:
                from posipaka.core.auto_update import AutoUpdater

                updater = AutoUpdater()
                info = await updater.check_for_updates()
                if info.update_available:
                    return updater.format_update_message(info)
                return f"Posipaka актуальна (v{info.current_version})."
            except Exception as e:
                return f"Помилка перевірки оновлень: {e}"
        if command == "complexity":
            if not self.complexity_manager:
                return "ComplexityManager не ініціалізований."
            if not args:
                return self.complexity_manager.format_status(user_id)
            if self.complexity_manager.set_level(user_id, args.strip()):
                return f"Рівень складності змінено на '{args.strip()}'."
            return (
                f"Невідомий рівень: '{args}'. "
                f"Доступні: {', '.join(self.complexity_manager.available_levels())}"
            )
        if command == "timezone" or command == "tz":
            if not self.timezone_manager:
                return "TimezoneManager не ініціалізований."
            if not args:
                return await self.timezone_manager.format_for_system_prompt(user_id)
            try:
                await self.timezone_manager.set_timezone(user_id, args.strip())
                now = await self.timezone_manager.get_user_time_str(user_id)
                return f"Часовий пояс змінено. Ваш поточний час: {now}"
            except ValueError:
                return f"Невідомий часовий пояс: '{args}'. Приклад: Europe/Kyiv, US/Eastern"
        return f"Невідома команда: /{command}"

    async def cleanup_expired_approvals(self) -> None:
        """Delegate to ApprovalGate."""
        await self.approval_gate.cleanup_expired()

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        self.status = AgentStatus.STOPPED
        if self.memory:
            await self.memory.close()
        self.audit.log("agent_stop", {})
        await self.hooks.emit(HookEvent.AGENT_STOP)
        logger.info("Agent stopped")

    def _format_status(self) -> str:
        tools_count = len(self.tools.list_tools())
        cost_report = self.cost_guard.get_daily_report()
        return (
            f"Posipaka Agent\n"
            f"Статус: {self.status.value}\n"
            f"LLM: {self.settings.llm.provider}/{self.settings.llm.model}\n"
            f"Інструментів: {tools_count}\n"
            f"\n{cost_report}"
        )


_ELICIT_RE = _re.compile(r"^\[elicit:([a-f0-9]+)\]\s*(.*)", _re.DOTALL)


def _match_elicitation_response(text: str) -> tuple[str, str] | None:
    m = _ELICIT_RE.match(text)
    if not m:
        return None
    return m.group(1), m.group(2)
