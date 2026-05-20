from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import yaml
from agentdojo.base_tasks import BaseInjectionTask, BaseUserTask
from agentdojo.functions_runtime import TaskEnvironment
from agentdojo.task_suite.task_suite import TaskSuite

from midojo.app.models import ToolInfoResponse
from midojo.attack_types import wrap_payload
from midojo.env_inference import infer_environment_type
from midojo.predicates import Predicate, evaluate_predicate, parse_predicate


class MiDojoInjectionTask(BaseInjectionTask):
    """MiDojo's injection task base. Replaces agentdojo's GOAL/attack model
    with a probes-based one.

    DESCRIPTION is human-readable documentation of what the injection aims to
    do (not consumed by code).

    PROBES maps probe_id to the final payload string — already wrapped by the
    probe's `attack_type` vehicle. Stored ready-to-substitute. The active
    task's probes are merged into the injections dict at orchestration time
    and substituted into `{task_id:probe_id}` placeholders in the environment.

    NOTE: subclassing agentdojo's BaseInjectionTask is awkward now that the
    attack layer is gone — what we inherit is mostly bureaucratic (numeric
    class-name constraint enforced by TaskSuite._get_task_number, unused
    GOAL annotation, unused BenchmarkVersion machinery). The plan is to
    drop this inheritance (and YAMLTaskSuite's TaskSuite inheritance) in
    a follow-up, which would also unlock descriptive task ids.
    """

    DESCRIPTION: str = ""
    PROBES: dict[str, str] = {}


# Matches `{task_id:probe_id}` placeholders. Identifiers only (letters, digits,
# underscore), so this won't collide with YAML content that happens to contain
# braces.
_PROBE_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_]\w*):([A-Za-z_]\w*)\}")


class YAMLTaskSuite(TaskSuite):
    """TaskSuite subclass that reads everything from a single suite.yaml."""

    def __init__(
        self,
        name: str,
        suite_yaml_path: Path,
        environment_type: type[TaskEnvironment] | None = None,
    ) -> None:
        self._suite_yaml_path = suite_yaml_path
        self._suite_raw: dict = yaml.safe_load(suite_yaml_path.read_text())
        if environment_type is None:
            environment_type = infer_environment_type(name, self._suite_raw["environment"])
        # `tools` is a required positional arg on agentdojo's TaskSuite. We
        # don't model agent-callable tool *functions* (only their YAML-declared
        # names, for display), so we always pass [].
        super().__init__(name, environment_type, [], data_path=suite_yaml_path.parent)
        self._register_tasks()

    @property
    def injection_tasks(self) -> dict[str, MiDojoInjectionTask]:  # type: ignore[override]
        # Narrowing the value type from agentdojo's BaseInjectionTask to
        # MiDojoInjectionTask. dict is invariant so this isn't strictly
        # Liskov-safe, but every task we register goes through
        # _make_injection_task_class which produces MiDojoInjectionTask
        # instances, so the cast is sound in practice.
        return cast("dict[str, MiDojoInjectionTask]", super().injection_tasks)

    def load_and_inject_default_environment(self, injections: dict[str, str]) -> TaskEnvironment:
        """Render the env template with probe payloads substituted in.

        `injections` is a dict keyed by `"task_id:probe_id"`. Probes are
        scoped to a single injection task — `{task_id:probe_id}` placeholders
        for any task whose probe isn't in the dict collapse to "". (Typo
        detection — a `{task:probe}` pointing at nothing — is deferred.)
        """
        env_raw = self._suite_raw["environment"]
        env_text = yaml.dump(env_raw, default_flow_style=False)
        env_text = _PROBE_PLACEHOLDER_RE.sub(
            lambda m: injections.get(f"{m.group(1)}:{m.group(2)}", ""),
            env_text,
        )
        return self.environment_type.model_validate(yaml.safe_load(env_text))

    def get_probes_for_task(self, task_id: str) -> dict[str, str]:
        """Return probe payloads for an injection task, keyed as `task_id:probe_id`.

        Ready to merge into the injections dict consumed by
        `load_and_inject_default_environment`.
        """
        probes = self.injection_tasks[task_id].PROBES
        return {f"{task_id}:{probe_id}": payload for probe_id, payload in probes.items()}

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
            class_name = self._task_id_to_class_name(task_id, "UserTask")
            predicate = parse_predicate(task_raw["utility"])

            cls = self._make_user_task_class(
                class_name=class_name,
                prompt=task_raw["prompt"],
                predicate=predicate,
            )
            self.register_user_task(cls)

        for task_raw in self._suite_raw.get("injection_tasks", []):
            task_id = task_raw["id"]
            class_name = self._task_id_to_class_name(task_id, "InjectionTask")
            predicate = parse_predicate(task_raw["security"])
            probes = self._parse_probes(task_id, task_raw.get("probes", {}))

            cls = self._make_injection_task_class(
                class_name=class_name,
                description=task_raw["description"],
                predicate=predicate,
                probes=probes,
            )
            self.register_injection_task(cls)

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
                # Re-raise with the probe context so suite authors can locate the typo.
                raise ValueError(f"Probe '{task_id}:{probe_id}': {e}") from None
        return probes

    @staticmethod
    def _task_id_to_class_name(task_id: str, prefix: str) -> str:
        num = task_id.rsplit("_", 1)[-1]
        return f"{prefix}{num}"

    @staticmethod
    def _make_user_task_class(
        class_name: str,
        prompt: str,
        predicate: Predicate,
    ) -> type[BaseUserTask]:
        def ground_truth(self: Any, pre_environment: TaskEnvironment) -> list:
            return []

        def utility(
            self: Any,
            model_output: str,
            pre_environment: TaskEnvironment,
            post_environment: TaskEnvironment,
            strict: bool = True,
        ) -> bool:
            return evaluate_predicate(predicate, model_output, pre_environment, post_environment)

        return type(
            class_name,
            (BaseUserTask,),
            {
                "PROMPT": prompt,
                "ground_truth": ground_truth,
                "utility": utility,
            },
        )

    @staticmethod
    def _make_injection_task_class(
        class_name: str,
        description: str,
        predicate: Predicate,
        probes: dict[str, str],
    ) -> type[MiDojoInjectionTask]:
        def ground_truth(self: Any, pre_environment: TaskEnvironment) -> list:
            return []

        def security(
            self: Any,
            model_output: str,
            pre_environment: TaskEnvironment,
            post_environment: TaskEnvironment,
        ) -> bool:
            return evaluate_predicate(predicate, model_output, pre_environment, post_environment)

        return type(
            class_name,
            (MiDojoInjectionTask,),
            {
                "DESCRIPTION": description,
                "PROBES": probes,
                "ground_truth": ground_truth,
                "security": security,
            },
        )
