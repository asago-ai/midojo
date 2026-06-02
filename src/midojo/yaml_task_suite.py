from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from midojo.app.models import ToolInfoResponse
from midojo.attack_types import wrap_payload
from midojo.backends import EnvironmentBackend, build_backend
from midojo.probes import substitute_probes
from midojo.types import Environment, FunctionCallRecord
from midojo.verification import Check, VerificationContext, parse_check


@dataclass
class UserTask:
    id: str
    prompt: str
    check: Check


@dataclass
class InjectionTask:
    id: str
    description: str
    probes: dict[str, str] = field(default_factory=dict)
    check: Check | None = None


class YAMLTaskSuite:
    """Reads a suite definition from a single suite.yaml file."""

    def __init__(
        self,
        name: str,
        suite_yaml_path: Path,
        backend: EnvironmentBackend | None = None,
    ) -> None:
        self.name = name
        self._suite_yaml_path = suite_yaml_path
        self._suite_raw: dict = yaml.safe_load(suite_yaml_path.read_text())
        self.backend: EnvironmentBackend = backend or build_backend(name, self._suite_raw["environment"])
        self.user_tasks: dict[str, UserTask] = {}
        self.injection_tasks: dict[str, InjectionTask] = {}
        self._register_tasks()

    @property
    def environment_type(self) -> type[Environment]:
        return self.backend.environment_type

    def provision_environment(self, injections: dict[str, str]) -> Environment:
        return self.backend.provision(injections)

    def inject_user_task_prompt(self, user_task_id: str, injections: dict[str, str]) -> str:
        return substitute_probes(self.user_tasks[user_task_id].prompt, injections)

    def get_probes_for_task(self, task_id: str) -> dict[str, str]:
        probes = self.injection_tasks[task_id].probes
        return {f"{task_id}:{probe_id}": payload for probe_id, payload in probes.items()}

    def grade(
        self,
        user_task_id: str,
        injection_task_id: str | None,
        agent_output: str,
        pre_environment: Environment,
        post_environment: Environment,
        function_calls: list[FunctionCallRecord],
    ) -> dict[str, bool]:
        ctx = VerificationContext(
            agent_output=agent_output,
            pre_environment=pre_environment,
            post_environment=post_environment,
            function_calls=function_calls,
        )

        utility = self.user_tasks[user_task_id].check.evaluate(ctx)

        injection_check = self.injection_tasks[injection_task_id].check if injection_task_id is not None else None
        security = injection_check.evaluate(ctx) if injection_check is not None else False

        return {"utility": utility, "security": security}

    def get_tool_definitions(self) -> list[ToolInfoResponse]:
        return [
            ToolInfoResponse(
                name=t["name"],
                description=t.get("description", ""),
                parameters=t.get("parameters", {}),
            )
            for t in self._suite_raw.get("tools", [])
        ]

    def get_tool_names(self) -> list[str]:
        return [t["name"] for t in self._suite_raw.get("tools", [])]

    def _register_tasks(self) -> None:
        for task_raw in self._suite_raw.get("user_tasks", []):
            task_id = task_raw["id"]
            check = parse_check(task_raw["utility"])
            self.user_tasks[task_id] = UserTask(id=task_id, prompt=task_raw["prompt"], check=check)

        for task_raw in self._suite_raw.get("injection_tasks", []):
            task_id = task_raw["id"]
            check = parse_check(task_raw["security"])
            probes = self._parse_probes(task_id, task_raw.get("probes", {}))
            self.injection_tasks[task_id] = InjectionTask(
                id=task_id,
                description=task_raw["description"],
                check=check,
                probes=probes,
            )

    @staticmethod
    def _parse_probes(task_id: str, raw: dict[str, dict]) -> dict[str, str]:
        probes: dict[str, str] = {}
        for probe_id, probe_raw in raw.items():
            if "payload" not in probe_raw:
                raise ValueError(f"Probe '{task_id}:{probe_id}' is missing required 'payload' field")
            attack_type = probe_raw.get("attack_type", "verbatim")
            try:
                probes[probe_id] = wrap_payload(probe_raw["payload"], attack_type)
            except ValueError as e:
                raise ValueError(f"Probe '{task_id}:{probe_id}': {e}") from None
        return probes
