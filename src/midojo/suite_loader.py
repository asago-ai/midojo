from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from agentdojo.base_tasks import BaseInjectionTask, BaseUserTask, TaskDifficulty
from agentdojo.functions_runtime import FunctionCall

from midojo.predicates import Predicate, evaluate_predicate, parse_predicate

_DIFFICULTY_MAP = {
    "easy": TaskDifficulty.EASY,
    "medium": TaskDifficulty.MEDIUM,
    "hard": TaskDifficulty.HARD,
}


def _parse_ground_truth_calls(raw_list: list[dict]) -> list[FunctionCall]:
    return [
        FunctionCall(
            function=item["function"],
            args=item.get("args", {}),
            placeholder_args=item.get("placeholder_args"),
        )
        for item in raw_list
    ]


def _make_user_task_class(
    class_name: str,
    prompt: str,
    ground_truth_output: str,
    difficulty: TaskDifficulty,
    gt_calls: list[FunctionCall],
    predicate: Predicate,
) -> type[BaseUserTask]:
    def ground_truth(self: Any, pre_environment: Any) -> list[FunctionCall]:
        return list(gt_calls)

    def utility(
        self: Any,
        model_output: str,
        pre_environment: Any,
        post_environment: Any,
        strict: bool = True,
    ) -> bool:
        pre = pre_environment.model_dump() if hasattr(pre_environment, "model_dump") else pre_environment
        post = post_environment.model_dump() if hasattr(post_environment, "model_dump") else post_environment
        return evaluate_predicate(predicate, model_output, pre, post)

    cls = type(
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
    return cls


def _make_injection_task_class(
    class_name: str,
    goal: str,
    difficulty: TaskDifficulty,
    gt_calls: list[FunctionCall],
    predicate: Predicate,
) -> type[BaseInjectionTask]:
    def ground_truth(self: Any, pre_environment: Any) -> list[FunctionCall]:
        return list(gt_calls)

    def security(
        self: Any,
        model_output: str,
        pre_environment: Any,
        post_environment: Any,
    ) -> bool:
        pre = pre_environment.model_dump() if hasattr(pre_environment, "model_dump") else pre_environment
        post = post_environment.model_dump() if hasattr(post_environment, "model_dump") else post_environment
        return evaluate_predicate(predicate, model_output, pre, post)

    cls = type(
        class_name,
        (BaseInjectionTask,),
        {
            "GOAL": goal,
            "DIFFICULTY": difficulty,
            "ground_truth": ground_truth,
            "security": security,
        },
    )
    return cls


def _task_id_to_class_name(task_id: str, prefix: str) -> str:
    """Convert e.g. 'user_task_0' -> 'UserTask0' for agentdojo's naming convention."""
    num = task_id.rsplit("_", 1)[-1]
    return f"{prefix}{num}"


def register_tasks_from_suite_yaml(suite: Any, suite_yaml_path: Path) -> None:
    """Read suite.yaml and register user/injection tasks on the given TaskSuite."""
    raw = yaml.safe_load(suite_yaml_path.read_text())

    for task_raw in raw.get("user_tasks", []):
        task_id = task_raw["id"]
        class_name = _task_id_to_class_name(task_id, "UserTask")
        difficulty = _DIFFICULTY_MAP.get(task_raw.get("difficulty", "easy"), TaskDifficulty.EASY)
        gt_calls = _parse_ground_truth_calls(task_raw.get("ground_truth", []))
        predicate = parse_predicate(task_raw["utility"])

        cls = _make_user_task_class(
            class_name=class_name,
            prompt=task_raw["prompt"],
            ground_truth_output=task_raw.get("ground_truth_output", ""),
            difficulty=difficulty,
            gt_calls=gt_calls,
            predicate=predicate,
        )
        suite.register_user_task(cls)

    for task_raw in raw.get("injection_tasks", []):
        task_id = task_raw["id"]
        class_name = _task_id_to_class_name(task_id, "InjectionTask")
        difficulty = _DIFFICULTY_MAP.get(task_raw.get("difficulty", "easy"), TaskDifficulty.EASY)
        gt_calls = _parse_ground_truth_calls(task_raw.get("ground_truth", []))
        predicate = parse_predicate(task_raw["security"])

        cls = _make_injection_task_class(
            class_name=class_name,
            goal=task_raw["goal"],
            difficulty=difficulty,
            gt_calls=gt_calls,
            predicate=predicate,
        )
        suite.register_injection_task(cls)
