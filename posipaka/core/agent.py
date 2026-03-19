"""Головний Agent клас — agentic loop."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from loguru import logger

from posipaka.config.settings import Settings
from posipaka.core.cost_guard import CostGuard
from posipaka.core.hooks.manager import HookEvent, HookManager
from posipaka.core.model_router import ModelRouter
from posipaka.core.semantic_cache import SemanticResponseCache
from posipaka.core.session import SessionManager
from posipaka.core.tools.compressor import ToolOutputCompressor
from posipaka.core.tools.registry import ToolRegistry
from posipaka.memory.manager import MemoryManager
from posipaka.security.audit import AuditLogger
from posipaka.security.injection import InjectionDetector


class AgentStatus(StrEnum):
    INITIALIZING = "initializing"
    READY = "ready"
    PROCESSING = "processing"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class Message:
    role: str
    content: str
    channel: str = "cli"
    user_id: str = ""
    username: str = ""
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    message_id: str = ""


@dataclass
class PendingAction:
    id: str
    tool_name: str
    tool_input: dict
    session_id: str
    user_id: str
    description: str
    created_at: float = field(default_factory=time.time)


_PROVIDER_BASE_URLS: dict[str, str] = {
    "mistral": "https://api.mistral.ai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "xai": "https://api.x.ai/v1",
}


class LLMClient:
    """Абстракція над LLM провайдерами (Anthropic / OpenAI / Ollama + OpenAI-сумісні)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._primary_client: Any = None
        self._fallback_client: Any = None

    def reinitialize(self) -> None:
        """Скинути кешовані клієнти — наступний complete() створить нових."""
        self._primary_client = None
        self._fallback_client = None
        logger.info("LLM client reset — will reinitialize on next call")

    def _init_clients(self) -> None:
        provider = self._settings.llm.provider
        api_key = self._settings.llm.api_key.get_secret_value()

        if provider == "anthropic" and api_key:
            try:
                import anthropic

                self._primary_client = anthropic.AsyncAnthropic(api_key=api_key)
            except ImportError:
                logger.warning("anthropic package not installed")
        elif provider == "openai" and api_key:
            try:
                import openai

                self._primary_client = openai.AsyncOpenAI(api_key=api_key)
            except ImportError:
                logger.warning("openai package not installed")
        elif provider == "ollama":
            try:
                import openai

                base_url = self._settings.llm.base_url or "http://localhost:11434/v1"
                self._primary_client = openai.AsyncOpenAI(base_url=base_url, api_key="ollama")
            except ImportError:
                logger.warning("openai package not installed")
        elif provider in _PROVIDER_BASE_URLS and api_key:
            try:
                import openai

                self._primary_client = openai.AsyncOpenAI(
                    base_url=_PROVIDER_BASE_URLS[provider],
                    api_key=api_key,
                )
            except ImportError:
                logger.warning("openai package not installed")

    async def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ) -> dict:
        """
        Виклик LLM.

        Returns: {content, stop_reason, tool_use, usage}
        """
        if self._primary_client is None:
            self._init_clients()

        provider = self._settings.llm.provider
        model = model or self._settings.llm.model

        try:
            if provider == "anthropic":
                return await self._call_anthropic(system, messages, tools, model)
            else:
                return await self._call_openai(system, messages, tools, model)
        except Exception as e:
            logger.error(f"LLM primary error: {e}")
            # Try fallback
            if self._settings.llm.fallback_provider:
                logger.info("Switching to fallback LLM")
                try:
                    return await self._call_fallback(system, messages, tools)
                except Exception as fe:
                    logger.error(f"LLM fallback error: {fe}")
            raise

    async def _call_anthropic(
        self, system: str, messages: list[dict], tools: list[dict] | None, model: str
    ) -> dict:
        if self._primary_client is None:
            raise RuntimeError("Anthropic client not initialized")

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": self._settings.llm.max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self._primary_client.messages.create(**kwargs)

        content = ""
        tool_use: list[dict] = []
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_use.append(
                    {
                        "name": block.name,
                        "input": block.input,
                        "id": block.id,
                    }
                )

        return {
            "content": content,
            "stop_reason": response.stop_reason,
            "tool_use": tool_use,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        }

    async def _call_openai(
        self, system: str, messages: list[dict], tools: list[dict] | None, model: str
    ) -> dict:
        if self._primary_client is None:
            raise RuntimeError("OpenAI client not initialized")

        oai_messages = [{"role": "system", "content": system}]
        for msg in messages:
            oai_messages.append({"role": msg["role"], "content": msg["content"]})

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": oai_messages,
            "max_tokens": self._settings.llm.max_tokens,
        }
        if tools:
            kwargs["tools"] = [
                t
                if "type" in t
                else {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {}),
                    },
                }
                for t in tools
            ]

        response = await self._primary_client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        tool_use: list[dict] = []
        if choice.message.tool_calls:
            import json

            for tc in choice.message.tool_calls:
                tool_use.append(
                    {
                        "name": tc.function.name,
                        "input": json.loads(tc.function.arguments),
                        "id": tc.id,
                    }
                )

        return {
            "content": choice.message.content or "",
            "stop_reason": "tool_use" if tool_use else "end_turn",
            "tool_use": tool_use,
            "usage": {
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        }

    async def _call_fallback(
        self, system: str, messages: list[dict], tools: list[dict] | None
    ) -> dict:
        fb_provider = self._settings.llm.fallback_provider
        fb_model = self._settings.llm.fallback_model
        fb_key = self._settings.llm.fallback_api_key.get_secret_value()

        if fb_provider == "anthropic" and fb_key:
            import anthropic

            old_client = self._primary_client
            self._primary_client = anthropic.AsyncAnthropic(api_key=fb_key)
            try:
                return await self._call_anthropic(system, messages, tools, fb_model)
            finally:
                self._primary_client = old_client
        elif fb_provider == "openai" and fb_key:
            import openai

            old_client = self._primary_client
            self._primary_client = openai.AsyncOpenAI(api_key=fb_key)
            try:
                return await self._call_openai(system, messages, tools, fb_model)
            finally:
                self._primary_client = old_client
        elif fb_provider == "ollama":
            import openai

            old_client = self._primary_client
            self._primary_client = openai.AsyncOpenAI(
                base_url="http://localhost:11434/v1", api_key="ollama"
            )
            try:
                return await self._call_openai(system, messages, tools, fb_model)
            finally:
                self._primary_client = old_client
        elif fb_provider in _PROVIDER_BASE_URLS and fb_key:
            import openai

            old_client = self._primary_client
            self._primary_client = openai.AsyncOpenAI(
                base_url=_PROVIDER_BASE_URLS[fb_provider],
                api_key=fb_key,
            )
            try:
                return await self._call_openai(system, messages, tools, fb_model)
            finally:
                self._primary_client = old_client

        raise RuntimeError("No fallback LLM available")


class Agent:
    """Головний агент Posipaka."""

    MAX_TOOL_LOOPS = 10
    MAX_CONTEXT_MESSAGES = 50

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
        self.heartbeat = None

    async def initialize(self) -> None:
        """Ініціалізація всіх підсистем."""
        self.settings.ensure_data_dir()

        # 1. Memory
        self.memory = MemoryManager(
            sqlite_path=self.settings.sqlite_db_path,
            chroma_path=self.settings.chroma_db_path,
            memory_md_path=self.settings.memory_md_path,
            short_term_limit=self.settings.memory.short_term_limit,
            chroma_enabled=self.settings.memory.chroma_enabled,
        )
        await self.memory.init()

        # 2. Load integrations + builtin skills
        self.tools.load_all_integrations()
        self._load_builtin_skills()

        # 3. Multi-agent orchestrator
        self._init_orchestrator()

        # 4. Persona manager
        self._init_personas()

        # 5. Cron engine (persistent)
        self._init_cron_engine()

        # 6. Create default files
        self._ensure_default_files()

        # 7. Advanced modules
        self._init_advanced_modules()

        # 8. Background update check
        self._schedule_update_check()

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
        """Ініціалізація persistent cron engine."""
        try:
            from posipaka.core.cron_engine import CronEngine

            cron_dir = self.settings.data_dir / "cron"
            self.cron_engine = CronEngine(cron_dir)
            self.cron_engine.init()
            logger.debug(f"CronEngine: {len(self.cron_engine.list_jobs())} jobs loaded")
        except Exception as e:
            logger.warning(f"CronEngine init error: {e}")

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
        """Створити SOUL.md, USER.md, MEMORY.md якщо не існують."""
        from posipaka.config.defaults import (
            HEARTBEAT_DEFAULT_CONTENT,
            MEMORY_DEFAULT_CONTENT,
            SOUL_DEFAULT_CONTENT,
            USER_DEFAULT_CONTENT,
        )

        heartbeat_path = self.settings.data_dir / "HEARTBEAT.md"
        for path, content in [
            (self.settings.soul_md_path, SOUL_DEFAULT_CONTENT),
            (self.settings.user_md_path, USER_DEFAULT_CONTENT),
            (self.settings.memory_md_path, MEMORY_DEFAULT_CONTENT),
            (heartbeat_path, HEARTBEAT_DEFAULT_CONTENT),
        ]:
            if not path.exists():
                path.write_text(content, encoding="utf-8")

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

            # Check pending approvals
            if content.lower().strip() in ("так", "yes", "ні", "no", "cancel"):
                result = await self._handle_approval_response(content, session_id)
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
            assert self.memory is not None
            await self.memory.add(session_id, {"role": "user", "content": content})

            # Build system prompt (з persona addon якщо активна)
            system_prompt = await self._build_system_prompt(session_id)
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
            recent = await self.memory.get_recent(session_id, self.MAX_CONTEXT_MESSAGES)
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

            # Get tool schemas
            tool_schemas = self.tools.get_schemas(self.settings.llm.provider)

            # Model routing — вибрати оптимальну модель + settings
            selected_profile = self.model_router.select_profile(
                content,
                tools_count=len(tool_schemas),
            )
            selected_model = selected_profile.model

            # Agentic loop
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
                try:
                    response = await self.llm.complete(
                        system=system_prompt,
                        messages=messages,
                        tools=tool_schemas if tool_schemas else None,
                        model=selected_model,
                    )
                    if self.degradation:
                        self.degradation.report_recovery("llm")
                except Exception as e:
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

                # If text response — done
                if response["stop_reason"] == "end_turn" or not response["tool_use"]:
                    text = response["content"]
                    if text:
                        response_time = time.time() - msg_start_time
                        await self.memory.add(session_id, {"role": "assistant", "content": text})
                        await self.memory.maybe_extract_facts(session_id, content)
                        # Cache response for similar future queries
                        await self.semantic_cache.store(content, text, session_id)
                        self.audit.log("response_sent", {"content": text})
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
                    if self._requires_approval(tool_name, tool_input):
                        action = PendingAction(
                            id=str(uuid.uuid4()),
                            tool_name=tool_name,
                            tool_input=tool_input,
                            session_id=session_id,
                            user_id="",
                            description=self.tools.describe_action(tool_name, tool_input),
                        )
                        self._pending_approvals[action.id] = action
                        self.audit.log(
                            "approval_requested",
                            {
                                "action_id": action.id,
                                "tool": tool_name,
                            },
                        )
                        await self.hooks.emit(
                            HookEvent.APPROVAL_REQUESTED,
                            {
                                "action": action,
                            },
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
                    except Exception as e:
                        result_str = f"Error: {e}"
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
                        messages.append(
                            {
                                "role": "assistant",
                                "content": f"[Tool: {tool_name}] → {result_str}",
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
            jobs = self.cron_engine.list_jobs()
            if not jobs:
                return "Немає запланованих завдань."
            lines = ["Заплановані завдання:"]
            for j in jobs:
                status = "✅" if j["enabled"] else "❌"
                lines.append(f"  {status} {j['name']} [{j['type']}] — {j['schedule']}")
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

    async def _build_system_prompt(self, session_id: str) -> str:
        """Побудова system prompt з SOUL.md + USER.md + MEMORY.md + semantic search."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        parts = []

        # Current date/time — щоб модель знала поточну дату
        try:
            tz = ZoneInfo(self.settings.soul.timezone)
        except (KeyError, ImportError):
            tz = ZoneInfo("UTC")
        now = datetime.now(tz)
        parts.append(f"Поточна дата: {now.strftime('%Y-%m-%d %H:%M')} ({now.tzname()})")

        # SOUL.md
        soul_path = self.settings.soul_md_path
        if soul_path.exists():
            parts.append(soul_path.read_text(encoding="utf-8"))

        # USER.md
        user_path = self.settings.user_md_path
        if user_path.exists():
            parts.append(user_path.read_text(encoding="utf-8"))

        # MEMORY.md — тільки релевантні факти
        if self.memory:
            memory_md = self.memory.get_memory_md()
            if memory_md:
                # Якщо MEMORY.md невеликий — включити цілком
                if len(memory_md) < 2000:
                    parts.append(f"# Пам'ять\n{memory_md}")
                else:
                    # Для великих MEMORY.md — включити тільки релевантні рядки
                    relevant_lines = self._select_relevant_facts(
                        memory_md,
                        session_id,
                    )
                    if relevant_lines:
                        parts.append(f"# Пам'ять (релевантне)\n{relevant_lines}")

        # Skill metadata
        skill_meta = self.tools.get_skill_metadata()
        if skill_meta:
            parts.append(skill_meta)

        return "\n\n---\n\n".join(parts)

    def _select_relevant_facts(
        self,
        memory_md: str,
        session_id: str,
    ) -> str:
        """Вибрати тільки релевантні факти з MEMORY.md."""
        lines = memory_md.strip().split("\n")
        # Always include headers and non-empty fact lines
        headers = [ln for ln in lines if ln.startswith("#")]
        facts = [ln for ln in lines if ln.strip() and not ln.startswith("#")]

        # If few facts, include all
        if len(facts) <= 10:
            return memory_md

        # Include last 10 facts (most recent) + all headers
        selected = headers + facts[-10:]
        return "\n".join(selected)

    async def _build_cached_system(self, session_id: str) -> list[dict]:
        """
        Структурований system prompt для Anthropic prompt caching.
        Статичний контент першим (кешується), динамічний останнім.
        """
        blocks = []

        # BLOCK 1: Статична особистість (кешується)
        soul_path = self.settings.soul_md_path
        if soul_path.exists():
            blocks.append(
                {
                    "type": "text",
                    "text": soul_path.read_text(encoding="utf-8"),
                    "cache_control": {"type": "ephemeral"},
                }
            )

        # BLOCK 2: Tools metadata (кешується — змінюється рідко)
        skill_meta = self.tools.get_skill_metadata()
        if skill_meta:
            blocks.append(
                {
                    "type": "text",
                    "text": f"# Available Skills\n{skill_meta}",
                    "cache_control": {"type": "ephemeral"},
                }
            )

        # BLOCK 3: User profile (кешується)
        user_path = self.settings.user_md_path
        if user_path.exists():
            blocks.append(
                {
                    "type": "text",
                    "text": user_path.read_text(encoding="utf-8"),
                    "cache_control": {"type": "ephemeral"},
                }
            )

        # BLOCK 4: Динамічна пам'ять (НЕ кешується)
        dynamic_parts = []
        if self.memory:
            memory_md = self.memory.get_memory_md()
            if memory_md:
                dynamic_parts.append(memory_md)
            relevant = await self.memory.search_relevant(session_id, "", 5)
            if relevant:
                dynamic_parts.append("\n".join(relevant))
        if dynamic_parts:
            blocks.append({"type": "text", "text": f"# Context\n{''.join(dynamic_parts)}"})

        return blocks

    def _requires_approval(self, tool_name: str, tool_input: dict) -> bool:
        """Чи потребує дія підтвердження."""
        tool_def = self.tools.get(tool_name)
        return bool(tool_def and tool_def.requires_approval)

    async def _handle_approval_response(self, content: str, session_id: str) -> str | None:
        """Обробити відповідь на approval."""
        # Find pending for this session
        for action_id, action in list(self._pending_approvals.items()):
            if action.session_id != session_id:
                continue

            # Check timeout
            if time.time() - action.created_at > self.settings.security.approval_timeout_seconds:
                del self._pending_approvals[action_id]
                return "Час підтвердження вичерпано. Дія скасована."

            lower = content.lower().strip()
            if lower in ("так", "yes"):
                del self._pending_approvals[action_id]
                self.audit.log("approval_granted", {"action_id": action_id})
                await self.hooks.emit(HookEvent.APPROVAL_GRANTED, {"action_id": action_id})
                try:
                    result = await self.tools.execute(action.tool_name, action.tool_input)
                    return f"Виконано: {result}"
                except Exception as e:
                    return f"Помилка при виконанні: {e}"
            elif lower in ("ні", "no", "cancel"):
                del self._pending_approvals[action_id]
                self.audit.log("approval_denied", {"action_id": action_id})
                await self.hooks.emit(HookEvent.APPROVAL_DENIED, {"action_id": action_id})
                return "Дію скасовано."

        return None

    async def cleanup_expired_approvals(self) -> None:
        """Видалити прострочені approval requests."""
        now = time.time()
        timeout = self.settings.security.approval_timeout_seconds
        expired = [
            aid
            for aid, action in self._pending_approvals.items()
            if now - action.created_at > timeout
        ]
        for aid in expired:
            action = self._pending_approvals.pop(aid)
            logger.info(f"Approval expired: {aid} ({action.tool_name})")
            self.audit.log("approval_expired", {"action_id": aid})

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
