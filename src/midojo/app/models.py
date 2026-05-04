from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Generic, TypeVar

from agentdojo.functions_runtime import FunctionsRuntime, TaskEnvironment
from pydantic import BaseModel

Env = TypeVar("Env", bound=TaskEnvironment)


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


# --- Run / Evaluation request/response models ---


class CreateEvaluationRequest(BaseModel):
    user_task_id: str
    injection_task_id: str | None = None
    injections: dict[str, str] = {}


class CreateRunResponse(BaseModel):
    id: str


class CreateEvaluationResponse(BaseModel):
    id: str
    prompt: str


class CompleteRequest(BaseModel):
    model_output: str


class GradeResponse(BaseModel):
    utility: bool
    security: bool


class EvaluationSummary(BaseModel):
    id: str
    user_task_id: str
    injection_task_id: str | None
    completed: bool
    utility: bool | None
    security: bool | None


class RunResponse(BaseModel):
    id: str
    created_at: str
    evaluations: list[EvaluationSummary]


class FunctionCallSummary(BaseModel):
    function: str
    args: dict
    result: str
    error: str | None
    timestamp: str


class FunctionCallResponse(FunctionCallSummary):
    pre_environment: dict
    post_environment: dict


class EvaluationResponse(BaseModel):
    id: str
    user_task_id: str
    injection_task_id: str | None
    completed: bool
    utility: bool | None
    security: bool | None
    model_output: str | None
    function_calls: list[FunctionCallSummary]


# --- Suite / task / tool response models ---


class UserTaskCheckResult(BaseModel):
    passed: bool
    message: str


class InjectionTaskCheckResult(BaseModel):
    passed: bool


class CheckResponse(BaseModel):
    passed: bool
    user_tasks: dict[str, UserTaskCheckResult]
    injection_tasks: dict[str, InjectionTaskCheckResult]


class InjectionVectorInfo(BaseModel):
    description: str
    default: str


class SuiteInfoResponse(BaseModel):
    user_tasks: list[str]
    injection_tasks: list[str]
    tools: list[str]
    injection_vectors: dict[str, InjectionVectorInfo]


class GroundTruthCall(BaseModel):
    function: str
    args: dict


class TaskDetailResponse(BaseModel):
    id: str
    type: str
    prompt: str | None = None
    goal: str | None = None
    ground_truth: list[GroundTruthCall]


class ToolInfoResponse(BaseModel):
    name: str
    description: str
    parameters: dict


# --- Internal state ---


@dataclass
class FunctionCallRecord:
    """A recorded function call execution, distinct from agentdojo's FunctionCall which represents just the intent (function + args)."""

    function: str
    args: dict
    result: str
    error: str | None
    timestamp: str
    pre_environment: dict = field(default_factory=dict)
    post_environment: dict = field(default_factory=dict)


@dataclass
class Evaluation(Generic[Env]):
    id: str
    user_task_id: str
    injection_task_id: str | None
    pre_environment: Env
    environment: Env
    runtime: FunctionsRuntime
    function_calls: list[FunctionCallRecord] = field(default_factory=list)
    model_output: str | None = None
    completed: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    active_injections: dict[str, str] = field(default_factory=dict)
    utility: bool | None = None
    security: bool | None = None


@dataclass
class Run:
    id: str
    evaluations: dict[str, Evaluation] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
