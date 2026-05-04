from __future__ import annotations

from typing import Annotated

from agentdojo.agent_pipeline.ground_truth_pipeline import GroundTruthPipeline
from agentdojo.functions_runtime import FunctionsRuntime
from fastapi import APIRouter, Depends, HTTPException, status

from midojo.yaml_task_suite import YAMLTaskSuite

from ..dependencies import get_suite
from ..models import GroundTruthCall, TaskDetailResponse

router = APIRouter(prefix="/tasks")


def _get_injection_candidates(suite: YAMLTaskSuite) -> dict[str, list[str]]:
    defaults = suite.get_injection_vector_defaults()
    canary_injections = {key: f"---CANARY_{key}---" for key in defaults}
    environment = suite.load_and_inject_default_environment(canary_injections)

    result: dict[str, list[str]] = {}
    for task_id, user_task in suite.user_tasks.items():
        pipeline = GroundTruthPipeline(user_task)
        runtime = FunctionsRuntime(suite.tools)
        _, _, _, responses, _ = pipeline.query(user_task.PROMPT, runtime, environment.model_copy(deep=True))

        tool_text = ""
        for msg in responses:
            if msg["role"] == "tool":
                for block in msg["content"]:
                    if isinstance(block, dict) and "content" in block:
                        tool_text += block["content"]
                    elif hasattr(block, "text"):
                        tool_text += block.text

        visible = [key for key, canary in canary_injections.items() if canary in tool_text]
        result[task_id] = visible

    return result


@router.get("/user", status_code=status.HTTP_200_OK)
def list_user_tasks(suite: Annotated[YAMLTaskSuite, Depends(get_suite)]) -> list[str]:
    return list(suite.user_tasks.keys())


@router.get("/user/{task_id}", response_model=TaskDetailResponse, status_code=status.HTTP_200_OK)
def get_user_task(task_id: str, suite: Annotated[YAMLTaskSuite, Depends(get_suite)]):
    if task_id not in suite.user_tasks:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown user task: {task_id}")
    task = suite.user_tasks[task_id]
    env = suite.load_and_inject_default_environment({})
    gt = task.ground_truth(env)
    return TaskDetailResponse(
        id=task_id,
        type="user",
        prompt=task.PROMPT,
        ground_truth=[GroundTruthCall(function=fc.function, args=fc.args) for fc in gt],
    )


@router.get("/injection", status_code=status.HTTP_200_OK)
def list_injection_tasks(suite: Annotated[YAMLTaskSuite, Depends(get_suite)]) -> list[str]:
    return list(suite.injection_tasks.keys())


@router.get("/injection/{task_id}", response_model=TaskDetailResponse, status_code=status.HTTP_200_OK)
def get_injection_task(task_id: str, suite: Annotated[YAMLTaskSuite, Depends(get_suite)]):
    if task_id not in suite.injection_tasks:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown injection task: {task_id}")
    task = suite.injection_tasks[task_id]
    env = suite.load_and_inject_default_environment({})
    gt = task.ground_truth(env)
    return TaskDetailResponse(
        id=task_id,
        type="injection",
        goal=task.GOAL,
        ground_truth=[GroundTruthCall(function=fc.function, args=fc.args) for fc in gt],
    )


@router.get("/injection-candidates", status_code=status.HTTP_200_OK)
def injection_candidates(suite: Annotated[YAMLTaskSuite, Depends(get_suite)]) -> dict[str, list[str]]:
    return _get_injection_candidates(suite)
