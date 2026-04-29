from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Generic, TypeVar

from agentdojo.functions_runtime import FunctionsRuntime, TaskEnvironment
from pydantic import BaseModel

Env = TypeVar("Env", bound=TaskEnvironment)


class SetupRequest(BaseModel):
    user_task_id: str
    injection_task_id: str | None = None
    injections: dict[str, str] = {}


class SetupResponse(BaseModel):
    status: str
    user_task_id: str
    injection_task_id: str | None


class StatusResponse(BaseModel):
    user_task_id: str | None
    injection_task_id: str | None
    tool_calls_count: int
    completed: bool


class CompleteRequest(BaseModel):
    model_output: str


class TraceResponse(BaseModel):
    trace: list[dict]


class GradeResponse(BaseModel):
    utility: bool
    security: bool


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


@dataclass
class TraceEntry:
    function: str
    args: dict
    result: str
    error: str | None
    timestamp: str


@dataclass
class BenchmarkSession(Generic[Env]):
    user_task_id: str
    injection_task_id: str | None
    pre_environment: Env
    environment: Env
    runtime: FunctionsRuntime
    trace: list[TraceEntry] = field(default_factory=list)
    model_output: str | None = None
    completed: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    active_injections: dict[str, str] = field(default_factory=dict)


class SessionHolder(Generic[Env]):
    def __init__(self) -> None:
        self.session: BenchmarkSession[Env] | None = None
