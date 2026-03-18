"""Structured output parsing та Chain of Verification для LLM відповідей."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any, TypeVar, Type

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

T = TypeVar("T", bound=BaseModel)


class ParseStrategy(StrEnum):
    JSON_BLOCK = "json_block"
    FULL_JSON = "full_json"
    YAML_BLOCK = "yaml_block"


# ---------------------------------------------------------------------------
# Structured output models
# ---------------------------------------------------------------------------


class AgentDecision(BaseModel):
    """Рішення LLM про наступну дію."""

    action: str  # "tool_call" | "respond" | "ask_clarification" | "delegate"
    reasoning: str
    confidence: float  # 0.0 - 1.0
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    delegate_to: str | None = None  # agent name


class TaskStep(BaseModel):
    """Один крок у плані задачі."""

    description: str
    tool: str | None = None
    args: dict[str, Any] | None = None
    depends_on: list[int] = Field(default_factory=list)
    parallel: bool = False


class TaskPlan(BaseModel):
    """Багатокроковий план виконання задачі."""

    goal: str
    steps: list[TaskStep]
    estimated_cost_usd: float = 0.0
    requires_approval: bool = False


class HeartbeatItem(BaseModel):
    """Один елемент з аналізу heartbeat."""

    source: str  # "gmail", "calendar", "news", etc.
    importance: str  # "low", "medium", "high", "critical"
    title: str
    details: str = ""


class HeartbeatAnalysis(BaseModel):
    """Результат аналізу heartbeat перевірки."""

    has_important_updates: bool
    summary: str
    items: list[HeartbeatItem] = Field(default_factory=list)
    recommended_action: str | None = None


class QualityScore(BaseModel):
    """Оцінка якості відповіді агента."""

    relevance: float  # 0-1
    accuracy: float  # 0-1
    helpfulness: float  # 0-1
    safety: float  # 0-1
    overall: float  # 0-1
    issues: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_structured_output(
    text: str,
    model: Type[T],
    strategy: ParseStrategy = ParseStrategy.JSON_BLOCK,
) -> T | None:
    """
    Парсить LLM output у Pydantic-модель.

    Пробує 3 стратегії по черзі:
    1. Витягти ```json ... ``` блок
    2. Парсити весь текст як JSON
    3. Витягти ```yaml ... ``` блок (якщо pyyaml доступний)
    """
    strategies = [ParseStrategy.JSON_BLOCK, ParseStrategy.FULL_JSON, ParseStrategy.YAML_BLOCK]
    if strategy != strategies[0]:
        strategies.remove(strategy)
        strategies.insert(0, strategy)

    for strat in strategies:
        try:
            data = _extract_data(text, strat)
            if data is not None:
                return model.model_validate(data)
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            logger.debug(f"Стратегія {strat} не спрацювала для {model.__name__}: {exc}")
            continue

    logger.warning(f"Жодна стратегія парсингу не спрацювала для {model.__name__}")
    return None


def _extract_data(text: str, strategy: ParseStrategy) -> dict | None:
    """Витягти словник з тексту відповідно до стратегії."""
    if strategy == ParseStrategy.JSON_BLOCK:
        match = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return None

    elif strategy == ParseStrategy.FULL_JSON:
        text = text.strip()
        if text.startswith("{"):
            return json.loads(text)
        return None

    elif strategy == ParseStrategy.YAML_BLOCK:
        match = re.search(r"```yaml\s*\n(.*?)```", text, re.DOTALL)
        if match:
            try:
                import yaml

                return yaml.safe_load(match.group(1))
            except ImportError:
                return None
        return None

    return None


# ---------------------------------------------------------------------------
# Chain of Verification (CoVe)
# ---------------------------------------------------------------------------


class _VerificationQuestions(BaseModel):
    questions: list[str]


class _VerificationResult(BaseModel):
    has_issues: bool
    issues: list[str] = Field(default_factory=list)
    corrected_response: str | None = None


class ChainOfVerification:
    """
    CoVe: верифікація LLM-відповідей для high-safety персон.

    Алгоритм:
    1. Згенерувати початкову відповідь
    2. Згенерувати верифікаційні питання
    3. Відповісти на кожне питання незалежно
    4. Перевірити на протиріччя
    5. Повернути верифіковану відповідь або зафіксувати проблеми
    """

    VERIFICATION_PROMPT = """You are a verification assistant. Given the following response,
generate 3 verification questions that would help confirm the accuracy of the claims made.

Response to verify:
{response}

Return as JSON: {{"questions": ["q1", "q2", "q3"]}}"""

    CHECK_PROMPT = """Given the original response and verification answers, identify any contradictions or inaccuracies.

Original response:
{response}

Verification Q&A:
{qa_pairs}

Return as JSON: {{
    "has_issues": true/false,
    "issues": ["issue1", ...],
    "corrected_response": "..." or null
}}"""

    def __init__(self, llm_call) -> None:
        """llm_call: async callable(system, prompt) -> str"""
        self._llm = llm_call

    async def verify(self, response: str) -> dict:
        """Запустити Chain of Verification на відповіді."""
        # Крок 1: Згенерувати верифікаційні питання
        q_result = await self._llm(
            "You are a fact-checker.",
            self.VERIFICATION_PROMPT.format(response=response),
        )
        questions_data = parse_structured_output(q_result, _VerificationQuestions)
        if not questions_data:
            return {"verified": True, "response": response, "issues": []}

        # Крок 2: Відповісти на кожне питання незалежно
        qa_pairs = []
        for q in questions_data.questions[:3]:
            answer = await self._llm(
                "Answer concisely and accurately.",
                q,
            )
            qa_pairs.append(f"Q: {q}\nA: {answer}")

        # Крок 3: Перевірити на протиріччя
        check_result = await self._llm(
            "You are a fact-checker.",
            self.CHECK_PROMPT.format(
                response=response,
                qa_pairs="\n\n".join(qa_pairs),
            ),
        )
        check_data = parse_structured_output(check_result, _VerificationResult)
        if check_data and check_data.has_issues:
            return {
                "verified": False,
                "response": check_data.corrected_response or response,
                "issues": check_data.issues,
            }

        return {"verified": True, "response": response, "issues": []}
