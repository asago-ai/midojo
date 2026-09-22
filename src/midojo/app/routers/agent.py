"""Callbacks used by the interception layer (MCP and framework SDKs).

Each callback's session token authorizes access to one evaluation.
"""

from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from midojo.types import SuiteName
from midojo.yaml_task_suite import YAMLTaskSuite

from ..dependencies import get_session_token, get_store, get_suites, resolve_suite, validate_environment
from ..models import CreateFunctionCallRecord, FunctionCallResponse, RecordObservationsRequest
from ..store import Store

router = APIRouter(prefix="/agent", dependencies=[Depends(get_session_token)])


@router.get("/environment")
def get_environment(
    session_token: Annotated[str, Depends(get_session_token)], store: Annotated[Store, Depends(get_store)]
) -> dict:
    with store.session_evaluation(session_token) as evaluation:
        return evaluation.environment.model_dump()


@router.put("/environment")
def put_environment(
    body: dict,
    session_token: Annotated[str, Depends(get_session_token)],
    store: Annotated[Store, Depends(get_store)],
    suites: Annotated[Mapping[SuiteName, YAMLTaskSuite], Depends(get_suites)],
) -> dict:
    with store.session_evaluation(session_token) as evaluation:
        run = store.get_run(evaluation.run_id)
        assert run is not None
        suite = resolve_suite(suites, run.suite_name, run.suite_version)
        env = validate_environment(suite, body)
        store.set_environment(run.id, evaluation.id, env)
        return env.model_dump()


@router.post("/function-calls", response_model=FunctionCallResponse, status_code=201)
def record_function_call(
    req: CreateFunctionCallRecord,
    session_token: Annotated[str, Depends(get_session_token)],
    store: Annotated[Store, Depends(get_store)],
) -> FunctionCallResponse:
    with store.session_evaluation(session_token) as evaluation:
        updated = store.append_function_call(evaluation.run_id, evaluation.id, req)
        assert updated is not None
        return FunctionCallResponse.model_validate(updated.function_calls[-1])


@router.get("/function-calls", response_model=list[FunctionCallResponse])
def list_function_calls(
    session_token: Annotated[str, Depends(get_session_token)], store: Annotated[Store, Depends(get_store)]
) -> list[FunctionCallResponse]:
    with store.session_evaluation(session_token) as evaluation:
        return [FunctionCallResponse.model_validate(call) for call in evaluation.function_calls]


@router.get("/function-calls/{idx}", response_model=FunctionCallResponse)
def get_function_call(
    idx: int, session_token: Annotated[str, Depends(get_session_token)], store: Annotated[Store, Depends(get_store)]
) -> FunctionCallResponse:
    with store.session_evaluation(session_token) as evaluation:
        if idx < 0 or idx >= len(evaluation.function_calls):
            raise HTTPException(404, f"Function call index out of range: {idx}")
        return FunctionCallResponse.model_validate(evaluation.function_calls[idx])


@router.post("/observations")
def record_observations(
    req: RecordObservationsRequest,
    session_token: Annotated[str, Depends(get_session_token)],
    store: Annotated[Store, Depends(get_store)],
) -> dict:
    with store.session_evaluation(session_token) as evaluation:
        store.record_observations(evaluation.run_id, evaluation.id, req.source, req.data)
        return dict(evaluation.observations)


@router.get("/observations")
def get_observations(
    session_token: Annotated[str, Depends(get_session_token)], store: Annotated[Store, Depends(get_store)]
) -> dict:
    with store.session_evaluation(session_token) as evaluation:
        return dict(evaluation.observations)
