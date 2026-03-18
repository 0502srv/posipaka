"""Workflow Engine — YAML-based workflows (секція 40 MASTER.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


@dataclass
class WorkflowStep:
    id: str
    tool: str | None = None
    llm: bool = False
    params: dict = field(default_factory=dict)
    prompt: str = ""
    input_from: str = ""  # output var from previous step
    output: str = ""  # var name for result
    condition: str = ""  # skip if condition false


@dataclass
class WorkflowDefinition:
    name: str
    description: str = ""
    schedule: str = ""  # cron
    trigger: str = "manual"
    steps: list[WorkflowStep] = field(default_factory=list)
    path: Path | None = None


class WorkflowEngine:
    """
    Виконує multi-step workflows.

    Формат: WORKFLOW.yaml з кроками що викликають tools та/або LLM.
    """

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowDefinition] = {}

    def load_file(self, path: Path) -> WorkflowDefinition | None:
        """Завантажити workflow з YAML."""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            steps = []
            for s in data.get("steps", []):
                steps.append(
                    WorkflowStep(
                        id=s.get("id", ""),
                        tool=s.get("tool"),
                        llm=s.get("llm", False),
                        params=s.get("params", {}),
                        prompt=s.get("prompt", ""),
                        input_from=s.get("input_from", ""),
                        output=s.get("output", ""),
                        condition=s.get("condition", ""),
                    )
                )
            wf = WorkflowDefinition(
                name=data.get("name", path.stem),
                description=data.get("description", ""),
                schedule=data.get("schedule", ""),
                trigger=data.get("trigger", "manual"),
                steps=steps,
                path=path,
            )
            self._workflows[wf.name] = wf
            return wf
        except Exception as e:
            logger.error(f"Error loading workflow {path}: {e}")
            return None

    def scan_directory(self, directory: Path) -> list[WorkflowDefinition]:
        """Завантажити всі workflows з директорії."""
        results = []
        if not directory.exists():
            return results
        for f in directory.glob("*.yaml"):
            wf = self.load_file(f)
            if wf:
                results.append(wf)
        for f in directory.glob("*.yml"):
            wf = self.load_file(f)
            if wf:
                results.append(wf)
        return results

    async def execute(
        self,
        name: str,
        tool_executor: Any = None,
        llm_fn: Any = None,
    ) -> dict[str, str]:
        """
        Виконати workflow.

        Args:
            name: назва workflow
            tool_executor: async fn(tool_name, params) -> str
            llm_fn: async fn(prompt) -> str
        """
        wf = self._workflows.get(name)
        if not wf:
            return {"error": f"Workflow '{name}' not found"}

        context: dict[str, str] = {}
        results: dict[str, str] = {}

        for step in wf.steps:
            # Check condition
            if step.condition and not self._eval_condition(step.condition, context):
                logger.debug(f"Workflow step skipped: {step.id}")
                continue

            # Resolve input
            params = dict(step.params)
            if step.input_from and step.input_from in context:
                params["input"] = context[step.input_from]

            # Execute
            try:
                if step.tool and tool_executor:
                    result = await tool_executor(step.tool, params)
                elif step.llm and llm_fn:
                    prompt = step.prompt
                    for key, val in context.items():
                        prompt = prompt.replace(f"{{{key}}}", val)
                    result = await llm_fn(prompt)
                else:
                    result = f"Step {step.id}: no executor"

                result_str = str(result)
                if step.output:
                    context[step.output] = result_str
                results[step.id] = result_str

                logger.debug(f"Workflow step done: {step.id}")
            except Exception as e:
                logger.error(f"Workflow step error {step.id}: {e}")
                results[step.id] = f"ERROR: {e}"
                break

        return results

    def list_workflows(self) -> list[dict]:
        return [
            {
                "name": w.name,
                "description": w.description,
                "schedule": w.schedule,
                "steps": len(w.steps),
            }
            for w in self._workflows.values()
        ]

    @staticmethod
    def _eval_condition(condition: str, context: dict) -> bool:
        """Проста перевірка умови (наявність змінної)."""
        # "has:unread_emails" → True if unread_emails in context
        if condition.startswith("has:"):
            var = condition[4:]
            return bool(context.get(var))
        return True
