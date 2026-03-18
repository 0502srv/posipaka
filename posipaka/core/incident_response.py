"""Incident Response — алертинг, інциденти та runbooks."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from loguru import logger

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AlertRule:
    """Правило алертингу для метрики."""

    name: str
    metric: str
    condition: str  # "gt", "lt", "eq"
    threshold: float
    cooldown_seconds: int = 300
    severity: str = "warning"  # "info", "warning", "critical"

    def evaluate(self, value: float) -> bool:
        """Перевірити чи метрика порушує правило."""
        if self.condition == "gt":
            return value > self.threshold
        if self.condition == "lt":
            return value < self.threshold
        if self.condition == "eq":
            return value == self.threshold
        logger.warning("Unknown alert condition: {}", self.condition)
        return False


@dataclass
class Incident:
    """Зареєстрований інцидент."""

    id: str
    alert_rule_name: str
    severity: str
    message: str
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False
    resolved_at: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "alert_rule_name": self.alert_rule_name,
            "severity": self.severity,
            "message": self.message,
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp).isoformat(),
            "resolved": self.resolved,
            "resolved_at": self.resolved_at,
        }


@dataclass
class Runbook:
    """Стандартна процедура реагування на алерт."""

    name: str
    description: str
    trigger: str  # alert rule name
    steps: list[str] = field(default_factory=list)
    auto_actions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Default alert rules
# ---------------------------------------------------------------------------

DEFAULT_ALERT_RULES: list[AlertRule] = [
    AlertRule(
        name="high_error_rate",
        metric="error_rate",
        condition="gt",
        threshold=0.1,
        cooldown_seconds=300,
        severity="critical",
    ),
    AlertRule(
        name="high_latency",
        metric="response_time",
        condition="gt",
        threshold=15.0,
        cooldown_seconds=300,
        severity="warning",
    ),
    AlertRule(
        name="budget_exceeded",
        metric="daily_cost",
        condition="gt",
        threshold=5.0,
        cooldown_seconds=600,
        severity="critical",
    ),
    AlertRule(
        name="memory_high",
        metric="memory_usage",
        condition="gt",
        threshold=0.9,
        cooldown_seconds=300,
        severity="warning",
    ),
    AlertRule(
        name="disk_low",
        metric="disk_free_gb",
        condition="lt",
        threshold=1.0,
        cooldown_seconds=600,
        severity="critical",
    ),
]

# ---------------------------------------------------------------------------
# Default runbooks
# ---------------------------------------------------------------------------

DEFAULT_RUNBOOKS: list[Runbook] = [
    Runbook(
        name="high_error_rate_runbook",
        description="Процедура при високому рівні помилок LLM.",
        trigger="high_error_rate",
        steps=[
            "posipaka status — підтвердити проблему",
            "Перевірити статус LLM провайдера",
            "posipaka config set LLM_PROVIDER <fallback> — переключити провайдер",
            "Якщо всі провайдери down — agent у MINIMAL mode",
            "Після відновлення — повернути основний провайдер",
        ],
        auto_actions=[
            "degradation_manager.set_mode(DEGRADED)",
            "notify_owner(telegram)",
        ],
    ),
    Runbook(
        name="high_latency_runbook",
        description="Процедура при високій латентності відповідей.",
        trigger="high_latency",
        steps=[
            "posipaka status — перевірити стан компонентів",
            "Перевірити навантаження CPU/RAM — posipaka resource status",
            "Перевірити кількість активних сесій",
            "Зменшити MAX_CONTEXT_MESSAGES якщо потрібно",
            "Перевірити чи працює semantic cache",
        ],
        auto_actions=[
            "prompt_compressor.enable()",
            "notify_owner(telegram)",
        ],
    ),
    Runbook(
        name="budget_exceeded_runbook",
        description="Процедура при перевищенні добового бюджету.",
        trigger="budget_exceeded",
        steps=[
            "posipaka cost stats — знайти причину",
            "Перевірити cron jobs — posipaka cron list",
            "Вимкнути підозрілі jobs — posipaka cron disable NAME",
            "Перевірити heartbeat частоту",
            "posipaka config set LLM_DAILY_BUDGET_USD 5.0 — встановити ліміт",
        ],
        auto_actions=[
            "cost_guard.enforce_hard_limit()",
            "notify_owner(telegram)",
        ],
    ),
    Runbook(
        name="memory_high_runbook",
        description="Процедура при високому використанні RAM.",
        trigger="memory_high",
        steps=[
            "posipaka resource status — перевірити деталі",
            "Перевірити кількість активних сесій",
            "Очистити semantic cache — posipaka cache clear",
            "Увімкнути мінімальний профіль — posipaka config set PROFILE minimal",
            "Якщо не допомагає — перезапустити агента",
        ],
        auto_actions=[
            "semantic_cache.clear()",
            "notify_owner(telegram)",
        ],
    ),
    Runbook(
        name="disk_low_runbook",
        description="Процедура при критично малому місці на диску.",
        trigger="disk_low",
        steps=[
            "posipaka resource status — перевірити деталі",
            "Очистити логи — posipaka logs clear --older-than 7d",
            "Очистити backups — posipaka backup prune --keep 3",
            "Перевірити розмір ChromaDB — du -sh ~/.posipaka/chroma/",
            "Якщо диск повний — перейти в read-only режим",
        ],
        auto_actions=[
            "degradation_manager.set_mode(DEGRADED)",
            "notify_owner(telegram)",
        ],
    ),
]


# ---------------------------------------------------------------------------
# IncidentManager
# ---------------------------------------------------------------------------


class IncidentManager:
    """
    Менеджер інцидентів — алертинг, реєстрація інцидентів, runbooks.

    Використання:
        manager = IncidentManager(data_dir=Path("~/.posipaka"))
        incidents = await manager.check_metric("error_rate", 0.15)
        for inc in incidents:
            runbook = manager.get_runbook(inc.alert_rule_name)
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir
        self._rules: dict[str, AlertRule] = {}
        self._runbooks: dict[str, Runbook] = {}
        self._incidents: list[Incident] = []
        self._last_fired: dict[str, float] = {}  # rule_name -> timestamp

        # Зареєструвати дефолтні правила та runbooks
        for rule in DEFAULT_ALERT_RULES:
            self.add_rule(rule)
        for runbook in DEFAULT_RUNBOOKS:
            self.add_runbook(runbook)

        # Спробувати завантажити збережені інциденти
        self._load_incidents()
        logger.info(
            "IncidentManager initialized: {} rules, {} runbooks",
            len(self._rules),
            len(self._runbooks),
        )

    # -- Rules ---------------------------------------------------------------

    def add_rule(self, rule: AlertRule) -> None:
        """Додати або замінити правило алертингу."""
        self._rules[rule.name] = rule
        logger.debug("Alert rule registered: {} ({})", rule.name, rule.severity)

    def remove_rule(self, name: str) -> bool:
        """Видалити правило."""
        if name in self._rules:
            del self._rules[name]
            return True
        return False

    # -- Runbooks ------------------------------------------------------------

    def add_runbook(self, runbook: Runbook) -> None:
        """Додати або замінити runbook."""
        self._runbooks[runbook.trigger] = runbook
        logger.debug("Runbook registered: {} -> {}", runbook.name, runbook.trigger)

    def get_runbook(self, alert_name: str) -> Runbook | None:
        """Отримати runbook за іменем алерту."""
        return self._runbooks.get(alert_name)

    # -- Metric check --------------------------------------------------------

    async def check_metric(self, metric: str, value: float) -> list[Incident]:
        """
        Перевірити всі правила для метрики.

        Повертає список нових інцидентів якщо якесь правило спрацювало.
        Cooldown запобігає дублюванню алертів.
        """
        new_incidents: list[Incident] = []
        now = time.time()

        for rule in self._rules.values():
            if rule.metric != metric:
                continue

            if not rule.evaluate(value):
                continue

            # Cooldown check
            last = self._last_fired.get(rule.name, 0.0)
            if now - last < rule.cooldown_seconds:
                logger.debug(
                    "Alert {} in cooldown ({:.0f}s remaining)",
                    rule.name,
                    rule.cooldown_seconds - (now - last),
                )
                continue

            # Створити інцидент
            incident = Incident(
                id=uuid.uuid4().hex[:12],
                alert_rule_name=rule.name,
                severity=rule.severity,
                message=(
                    f"Alert [{rule.severity.upper()}] {rule.name}: "
                    f"{metric}={value} {rule.condition} {rule.threshold}"
                ),
                timestamp=now,
            )

            self._incidents.append(incident)
            self._last_fired[rule.name] = now
            new_incidents.append(incident)

            logger.warning(
                "Incident created: {} [{}] — {}",
                incident.id,
                incident.severity,
                incident.message,
            )

            # Логувати пов'язаний runbook
            runbook = self.get_runbook(rule.name)
            if runbook:
                logger.info(
                    "Runbook available for {}: {} ({} steps, {} auto_actions)",
                    rule.name,
                    runbook.name,
                    len(runbook.steps),
                    len(runbook.auto_actions),
                )

        if new_incidents:
            self._save_incidents()

        return new_incidents

    # -- Incidents -----------------------------------------------------------

    def get_active_incidents(self) -> list[Incident]:
        """Повернути всі невирішені інциденти."""
        return [inc for inc in self._incidents if not inc.resolved]

    def resolve_incident(self, incident_id: str) -> bool:
        """Позначити інцидент як вирішений."""
        for inc in self._incidents:
            if inc.id == incident_id and not inc.resolved:
                inc.resolved = True
                inc.resolved_at = time.time()
                logger.info("Incident resolved: {} ({})", inc.id, inc.alert_rule_name)
                self._save_incidents()
                return True
        logger.warning("Incident not found or already resolved: {}", incident_id)
        return False

    # -- Report --------------------------------------------------------------

    def get_report(self) -> dict:
        """Згенерувати звіт по інцидентах."""
        active = self.get_active_incidents()
        resolved = [inc for inc in self._incidents if inc.resolved]

        severity_counts: dict[str, int] = {}
        for inc in self._incidents:
            severity_counts[inc.severity] = severity_counts.get(inc.severity, 0) + 1

        rule_counts: dict[str, int] = {}
        for inc in self._incidents:
            rule_counts[inc.alert_rule_name] = rule_counts.get(inc.alert_rule_name, 0) + 1

        return {
            "total_incidents": len(self._incidents),
            "active_incidents": len(active),
            "resolved_incidents": len(resolved),
            "severity_counts": severity_counts,
            "rule_counts": rule_counts,
            "rules_registered": len(self._rules),
            "runbooks_registered": len(self._runbooks),
            "active": [inc.to_dict() for inc in active],
        }

    # -- Persistence ---------------------------------------------------------

    def _incidents_path(self) -> Path | None:
        if self._data_dir is None:
            return None
        return self._data_dir / "incidents.json"

    def _load_incidents(self) -> None:
        """Завантажити збережені інциденти з файлу."""
        path = self._incidents_path()
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data:
                self._incidents.append(
                    Incident(
                        id=item["id"],
                        alert_rule_name=item["alert_rule_name"],
                        severity=item["severity"],
                        message=item["message"],
                        timestamp=item["timestamp"],
                        resolved=item.get("resolved", False),
                        resolved_at=item.get("resolved_at"),
                    )
                )
            logger.debug("Loaded {} incidents from {}", len(self._incidents), path)
        except Exception as exc:
            logger.warning("Failed to load incidents from {}: {}", path, exc)

    def _save_incidents(self) -> None:
        """Зберегти інциденти у файл."""
        path = self._incidents_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = [inc.to_dict() for inc in self._incidents]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.debug("Saved {} incidents to {}", len(self._incidents), path)
        except Exception as exc:
            logger.warning("Failed to save incidents to {}: {}", path, exc)
