"""Callbacks used by the interception layer (MCP and framework SDKs).

Each callback's session token authorizes access to one evaluation.
"""

from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from midojo.channels import Channel
from midojo.types import InjectionInstruction, SuiteName
from midojo.yaml_task_suite import YAMLTaskSuite

from ..dependencies import get_session_token, get_store, get_suites, resolve_suite, validate_environment
from ..models import CreateFunctionCallRecord, FunctionCallResponse, RecordObservationsRequest
from ..store import Store

router = APIRouter(prefix="/agent")


@router.get("/environment")
async def get_environment(
    session_token: Annotated[str, Depends(get_session_token)], store: Annotated[Store, Depends(get_store)]
) -> dict:
    evaluation = store.session_evaluation(session_token)
    return evaluation.environment.model_dump()


@router.put("/environment")
async def put_environment(
    body: dict,
    session_token: Annotated[str, Depends(get_session_token)],
    store: Annotated[Store, Depends(get_store)],
    suites: Annotated[Mapping[SuiteName, YAMLTaskSuite], Depends(get_suites)],
) -> dict:
    evaluation = store.session_evaluation(session_token)
    run = store.get_run(evaluation.run_id)
    assert run is not None
    suite = resolve_suite(suites, run.suite_name)
    env = validate_environment(suite, body)
    store.set_environment(run.id, evaluation.id, env)
    return env.model_dump()


@router.post("/function-calls", response_model=FunctionCallResponse, status_code=201)
async def record_function_call(
    req: CreateFunctionCallRecord,
    session_token: Annotated[str, Depends(get_session_token)],
    store: Annotated[Store, Depends(get_store)],
) -> FunctionCallResponse:
    evaluation = store.session_evaluation(session_token)
    updated = store.append_function_call(evaluation.run_id, evaluation.id, req)
    assert updated is not None
    return FunctionCallResponse.model_validate(updated.function_calls[-1])


@router.get("/function-calls", response_model=list[FunctionCallResponse])
async def list_function_calls(
    session_token: Annotated[str, Depends(get_session_token)], store: Annotated[Store, Depends(get_store)]
) -> list[FunctionCallResponse]:
    evaluation = store.session_evaluation(session_token)
    return [FunctionCallResponse.model_validate(call) for call in evaluation.function_calls]


@router.get("/function-calls/{idx}", response_model=FunctionCallResponse)
async def get_function_call(
    idx: int, session_token: Annotated[str, Depends(get_session_token)], store: Annotated[Store, Depends(get_store)]
) -> FunctionCallResponse:
    evaluation = store.session_evaluation(session_token)
    if idx < 0 or idx >= len(evaluation.function_calls):
        raise HTTPException(404, f"Function call index out of range: {idx}")
    return FunctionCallResponse.model_validate(evaluation.function_calls[idx])


@router.post("/observations")
async def record_observations(
    req: RecordObservationsRequest,
    session_token: Annotated[str, Depends(get_session_token)],
    store: Annotated[Store, Depends(get_store)],
) -> dict:
    evaluation = store.session_evaluation(session_token)
    store.record_observations(evaluation.run_id, evaluation.id, req.source, req.data)
    return dict(evaluation.observations)


@router.get("/observations")
async def get_observations(
    session_token: Annotated[str, Depends(get_session_token)], store: Annotated[Store, Depends(get_store)]
) -> dict:
    evaluation = store.session_evaluation(session_token)
    return dict(evaluation.observations)


@router.get("/injection-plan", response_model=list[InjectionInstruction])
async def get_injection_plan(
    session_token: Annotated[str, Depends(get_session_token)],
    store: Annotated[Store, Depends(get_store)],
    channel: Channel | None = None,
) -> list[InjectionInstruction]:
    """The active evaluation's injection plan, optionally narrowed to one channel.

    This is how an interception adapter (a fake MCP server, a Claude Code hook)
    reads the payloads it must deliver. The plan is written elsewhere -- derived
    from the suite at evaluation creation, or replaced by id via
    ``PUT /runs/.../injection-plan`` -- so this endpoint is read-only.
    """
    evaluation = store.session_evaluation(session_token)
    plan = evaluation.injection_plan
    if channel is not None:
        plan = [instruction for instruction in plan if instruction.channel == channel]
    return plan
