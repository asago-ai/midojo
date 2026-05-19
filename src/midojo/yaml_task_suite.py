from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import yaml
from agentdojo.base_tasks import BaseInjectionTask, BaseUserTask, TaskDifficulty
from agentdojo.functions_runtime import Function, FunctionCall, TaskEnvironment
from agentdojo.task_suite.task_suite import TaskSuite, validate_injections

from midojo.app.models import InjectionVectorInfo, ToolInfoResponse
from midojo.env_inference import infer_environment_type
from midojo.predicates import Predicate, evaluate_predicate, parse_predicate


class MiDojoInjectionTask(BaseInjectionTask):
    """MiDojo's injection task base. Adds PROBES on top of agentdojo's contract.

    PROBES maps probe_id to inline payload text. The active injection task's
    probes are merged into the injections dict at orchestration time and
    substituted into `{task_id:probe_id}` placeholders in the environment.
    """

    PROBES: dict[str, str] = {}

_DIFFICULTY_MAP = {
    "easy": TaskDifficulty.EASY,
    "medium": TaskDifficulty.MEDIUM,
    "hard": TaskDifficulty.HARD,
}

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
        tools: list[Function] | None = None,
    ) -> None:
        self._suite_yaml_path = suite_yaml_path
        self._suite_raw: dict = yaml.safe_load(suite_yaml_path.read_text())
        if environment_type is None:
            environment_type = infer_environment_type(name, self._suite_raw["environment"])
        super().__init__(name, environment_type, tools or [], data_path=suite_yaml_path.parent)
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
        env_raw = self._suite_raw["environment"]
        env_text = yaml.dump(env_raw, default_flow_style=False)

        # Split into vector-style ({vector}) and probe-style ({task:probe}) keys.
        probe_injections = {k: v for k, v in injections.items() if ":" in k}
        vector_injections = {k: v for k, v in injections.items() if ":" not in k}

        # Probe placeholders use `:` which collides with str.format's format-spec
        # separator, so resolve them by regex first. Probes are scoped to a
        # single injection task — placeholders for any other task collapse to ""
        # so e.g. injection_task_2's primer doesn't leak into a run of
        # injection_task_0. (Typo detection — a `{task:probe}` pointing at
        # nothing — is deferred.)
        env_text = _PROBE_PLACEHOLDER_RE.sub(
            lambda m: probe_injections.get(f"{m.group(1)}:{m.group(2)}", ""),
            env_text,
        )

        injection_vector_defaults = self.get_injection_vector_defaults()
        injections_with_defaults = dict(injection_vector_defaults, **vector_injections)
        validate_injections(vector_injections, injection_vector_defaults)
        injected_text = env_text.format(**injections_with_defaults)
        return self.environment_type.model_validate(yaml.safe_load(injected_text))

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

    def get_injection_vector_defaults(self) -> dict[str, str]:
        vectors_raw = self._suite_raw.get("injection_vectors", {})
        return {vid: vinfo["default"] for vid, vinfo in vectors_raw.items()}

    def get_injection_vectors_raw(self) -> dict[str, dict[str, str]]:
        return self._suite_raw.get("injection_vectors", {})

    def get_injection_vector_info(self) -> dict[str, InjectionVectorInfo]:
        raw = self.get_injection_vectors_raw()
        return {vid: InjectionVectorInfo(description=v["description"], default=v["default"]) for vid, v in raw.items()}

    def _register_tasks(self) -> None:
        for task_raw in self._suite_raw.get("user_tasks", []):
            task_id = task_raw["id"]
            class_name = self._task_id_to_class_name(task_id, "UserTask")
            difficulty = _DIFFICULTY_MAP.get(task_raw.get("difficulty", "easy"), TaskDifficulty.EASY)
            gt_calls = self._parse_ground_truth_calls(task_raw.get("ground_truth", []))
            predicate = parse_predicate(task_raw["utility"])

            cls = self._make_user_task_class(
                class_name=class_name,
                prompt=task_raw["prompt"],
                ground_truth_output=task_raw.get("ground_truth_output", ""),
                difficulty=difficulty,
                gt_calls=gt_calls,
                predicate=predicate,
            )
            self.register_user_task(cls)

        for task_raw in self._suite_raw.get("injection_tasks", []):
            task_id = task_raw["id"]
            class_name = self._task_id_to_class_name(task_id, "InjectionTask")
            difficulty = _DIFFICULTY_MAP.get(task_raw.get("difficulty", "easy"), TaskDifficulty.EASY)
            gt_calls = self._parse_ground_truth_calls(task_raw.get("ground_truth", []))
            predicate = parse_predicate(task_raw["security"])
            probes = self._parse_probes(task_raw.get("probes", {}))

            cls = self._make_injection_task_class(
                class_name=class_name,
                goal=task_raw["goal"],
                difficulty=difficulty,
                gt_calls=gt_calls,
                predicate=predicate,
                probes=probes,
            )
            self.register_injection_task(cls)

    @staticmethod
    def _parse_ground_truth_calls(raw_list: list[dict]) -> list[FunctionCall]:
        return [
            FunctionCall(
                function=item["function"],
                args=item.get("args", {}),
                placeholder_args=item.get("placeholder_args"),
            )
            for item in raw_list
        ]

    @staticmethod
    def _parse_probes(raw: dict[str, dict]) -> dict[str, str]:
        probes: dict[str, str] = {}
        for probe_id, probe_raw in raw.items():
            if "payload" not in probe_raw:
                raise ValueError(f"Probe '{probe_id}' is missing required 'payload' field")
            probes[probe_id] = probe_raw["payload"]
        return probes

    @staticmethod
    def _task_id_to_class_name(task_id: str, prefix: str) -> str:
        num = task_id.rsplit("_", 1)[-1]
        return f"{prefix}{num}"

    @staticmethod
    def _make_user_task_class(
        class_name: str,
        prompt: str,
        ground_truth_output: str,
        difficulty: TaskDifficulty,
        gt_calls: list[FunctionCall],
        predicate: Predicate,
    ) -> type[BaseUserTask]:
        def ground_truth(self: Any, pre_environment: TaskEnvironment) -> list[FunctionCall]:
            return list(gt_calls)

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
                "GROUND_TRUTH_OUTPUT": ground_truth_output,
                "DIFFICULTY": difficulty,
                "ground_truth": ground_truth,
                "utility": utility,
            },
        )

    @staticmethod
    def _make_injection_task_class(
        class_name: str,
        goal: str,
        difficulty: TaskDifficulty,
        gt_calls: list[FunctionCall],
        predicate: Predicate,
        probes: dict[str, str],
    ) -> type[MiDojoInjectionTask]:
        def ground_truth(self: Any, pre_environment: TaskEnvironment) -> list[FunctionCall]:
            return list(gt_calls)

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
                "GOAL": goal,
                "DIFFICULTY": difficulty,
                "PROBES": probes,
                "ground_truth": ground_truth,
                "security": security,
            },
        )
