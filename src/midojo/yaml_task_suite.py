from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from midojo.app.models import ToolInfoResponse
from midojo.attack_types import wrap_payload
from midojo.env_inference import infer_environment_type
from midojo.predicates import Predicate, evaluate_predicate, parse_predicate
from midojo.types import Environment, FunctionCallRecord


@dataclass
class UserTask:
    id: str
    prompt: str
    predicate: Predicate

    def utility(self, agent_output: str, pre_env: Environment, post_env: Environment) -> bool:
        return evaluate_predicate(self.predicate, agent_output, pre_env, post_env)


@dataclass
class InjectionTask:
    id: str
    description: str
    probes: dict[str, str] = field(default_factory=dict)
    predicate: Predicate | None = None

    def security(self, agent_output: str, pre_env: Environment, post_env: Environment) -> bool:
        if self.predicate is None:
            return False
        return evaluate_predicate(self.predicate, agent_output, pre_env, post_env)


_PROBE_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_]\w*):([A-Za-z_]\w*)\}")


def _substitute_probes(text: str, injections: dict[str, str]) -> str:
    return _PROBE_PLACEHOLDER_RE.sub(
        lambda m: injections.get(f"{m.group(1)}:{m.group(2)}", ""),
        text,
    )


class YAMLTaskSuite:
    """Reads a suite definition from a single suite.yaml file."""

    def __init__(
        self,
        name: str,
        suite_yaml_path: Path,
        environment_type: type[Environment] | None = None,
    ) -> None:
        self.name = name
        self._suite_yaml_path = suite_yaml_path
        self._suite_raw: dict = yaml.safe_load(suite_yaml_path.read_text())
        if environment_type is None:
            environment_type = infer_environment_type(name, self._suite_raw["environment"])
        self.environment_type = environment_type
        self.user_tasks: dict[str, UserTask] = {}
        self.injection_tasks: dict[str, InjectionTask] = {}
        self._register_tasks()

    def load_and_inject_default_environment(self, injections: dict[str, str]) -> Environment:
        env_raw = self._suite_raw["environment"]
        env_text = yaml.dump(env_raw, default_flow_style=False, default_style='"')
        env_text = _substitute_probes(env_text, injections)
        return self.environment_type.model_validate(yaml.safe_load(env_text))

    def inject_user_task_prompt(self, user_task_id: str, injections: dict[str, str]) -> str:
        return _substitute_probes(self.user_tasks[user_task_id].prompt, injections)

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
        user_task = self.user_tasks[user_task_id]
        utility = user_task.utility(agent_output, pre_environment, post_environment)

        if injection_task_id is not None:
            injection_task = self.injection_tasks[injection_task_id]
            security = injection_task.security(agent_output, pre_environment, post_environment)
        else:
            security = False

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
            predicate = parse_predicate(task_raw["utility"])
            self.user_tasks[task_id] = UserTask(id=task_id, prompt=task_raw["prompt"], predicate=predicate)

        for task_raw in self._suite_raw.get("injection_tasks", []):
            task_id = task_raw["id"]
            predicate = parse_predicate(task_raw["security"])
            probes = self._parse_probes(task_id, task_raw.get("probes", {}))
            self.injection_tasks[task_id] = InjectionTask(
                id=task_id,
                description=task_raw["description"],
                predicate=predicate,
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
