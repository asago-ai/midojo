from __future__ import annotations

from agentdojo.functions_runtime import TaskEnvironment
from pydantic import BaseModel, ConfigDict


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


class FunctionCallRecord(BaseModel):
    """A recorded function call execution, distinct from agentdojo's
    FunctionCall which represents just the intent (function + args)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    function: str
    args: dict
    result: str
    error: str | None
    timestamp: str
    pre_environment: TaskEnvironment
    post_environment: TaskEnvironment


class EvaluationResponse(BaseModel):
    id: str
    user_task_id: str
    injection_task_id: str | None
    completed: bool
    utility: bool | None
    security: bool | None
    model_output: str | None
    function_calls: list[FunctionCallRecord]


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
    environment: TaskEnvironment


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
