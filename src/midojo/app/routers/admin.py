from __future__ import annotations

from types import ModuleType

import yaml
from agentdojo.agent_pipeline.ground_truth_pipeline import GroundTruthPipeline
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.task_suite import InjectionVector, TaskSuite, read_suite_file
from fastapi import APIRouter, HTTPException, status

from midojo.app.models import (
    CheckResponse,
    GroundTruthCall,
    InjectionTaskCheckResult,
    InjectionVectorInfo,
    SuiteInfoResponse,
    TaskDetailResponse,
    ToolInfoResponse,
    UserTaskCheckResult,
)


def _get_injection_vectors(suite: TaskSuite) -> dict[str, InjectionVector]:
    text = read_suite_file(suite.name, "injection_vectors.yaml", suite.data_path)
    raw = yaml.safe_load(text)
    return {vid: InjectionVector.model_validate(vinfo) for vid, vinfo in raw.items()}


def _get_injection_candidates(suite: TaskSuite) -> dict[str, list[str]]:
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


def create_admin_router(suite: TaskSuite, suite_module: ModuleType) -> APIRouter:
    router = APIRouter(prefix="/admin")

    @router.get("/check", response_model=CheckResponse, status_code=status.HTTP_200_OK)
    def check():
        passed, (user_results, injection_results) = suite.check(check_injectable=False)
        return CheckResponse(
            passed=passed,
            user_tasks={tid: UserTaskCheckResult(passed=ok, message=msg) for tid, (ok, msg) in user_results.items()},
            injection_tasks={tid: InjectionTaskCheckResult(passed=ok) for tid, ok in injection_results.items()},
        )

    @router.get("/injection-candidates", status_code=status.HTTP_200_OK)
    def injection_candidates() -> dict[str, list[str]]:
        return _get_injection_candidates(suite)

    @router.get("/environment", status_code=status.HTTP_200_OK)
    def environment() -> dict:
        env = suite.load_and_inject_default_environment({})
        return env.model_dump()

    @router.get("/suite", response_model=SuiteInfoResponse, status_code=status.HTTP_200_OK)
    def suite_info():
        vectors = _get_injection_vectors(suite)
        return SuiteInfoResponse(
            user_tasks=list(suite.user_tasks.keys()),
            injection_tasks=list(suite.injection_tasks.keys()),
            tools=[t.name for t in suite.tools],
            injection_vectors={
                vid: InjectionVectorInfo(description=v.description, default=v.default) for vid, v in vectors.items()
            },
        )

    @router.get("/tasks/{task_id}", response_model=TaskDetailResponse, status_code=status.HTTP_200_OK)
    def task_detail(task_id: str):
        env = suite.load_and_inject_default_environment({})

        if task_id in suite.user_tasks:
            task = suite.user_tasks[task_id]
            gt = task.ground_truth(env)
            return TaskDetailResponse(
                id=task_id,
                type="user",
                prompt=task.PROMPT,
                ground_truth=[GroundTruthCall(function=fc.function, args=fc.args) for fc in gt],
            )

        if task_id in suite.injection_tasks:
            task = suite.injection_tasks[task_id]
            gt = task.ground_truth(env)
            return TaskDetailResponse(
                id=task_id,
                type="injection",
                goal=task.GOAL,
                ground_truth=[GroundTruthCall(function=fc.function, args=fc.args) for fc in gt],
            )

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown task: {task_id}")

    @router.get("/tools", response_model=list[ToolInfoResponse], status_code=status.HTTP_200_OK)
    def tools():
        return [
            ToolInfoResponse(
                name=t.name,
                description=t.description or "",
                parameters={
                    "properties": {
                        name: {
                            "type": f.annotation.__name__ if hasattr(f.annotation, "__name__") else str(f.annotation)
                        }
                        for name, f in t.parameters.model_fields.items()
                    },
                    "required": [name for name, f in t.parameters.model_fields.items() if f.is_required()],
                },
            )
            for t in suite.tools
        ]

    return router
