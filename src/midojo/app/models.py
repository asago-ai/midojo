from __future__ import annotations

from pydantic import BaseModel

from midojo.types import Environment, FunctionCallRecord

# --- Run / Evaluation request/response models ---


class CreateFunctionCallRecord(BaseModel):
    """Request body for recording a function call (server fills in timestamp + env snapshots)."""

    function: str
    args: dict
    result: str
    error: str | None = None


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
    agent_output: str


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


class EvaluationResponse(BaseModel):
    id: str
    user_task_id: str
    injection_task_id: str | None
    completed: bool
    utility: bool | None
    security: bool | None
    agent_input: str | None
    agent_output: str | None
    function_calls: list[FunctionCallRecord]


# --- Suite / task / tool response models ---


class SuiteInfoResponse(BaseModel):
    user_tasks: list[str]
    injection_tasks: list[str]
    tools: list[str]
    environment: Environment


class TaskDetailResponse(BaseModel):
    id: str
    type: str
    prompt: str | None = None
    description: str | None = None


class ToolInfoResponse(BaseModel):
    name: str
    description: str
    parameters: dict
