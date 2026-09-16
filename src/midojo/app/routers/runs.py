from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from midojo.types import FunctionCallRecord
from midojo.yaml_task_suite import YAMLTaskSuite

from ..catalog import SuiteCatalog
from ..config import AppConfig
from ..dependencies import (
    get_catalog,
    get_config,
    get_evaluation_by_id,
    get_run,
    get_run_suite,
    get_store,
    resolve_suite,
    validate_environment,
)
from ..models import (
    CompleteRequest,
    CreateEvaluationRequest,
    CreateEvaluationResponse,
    CreateFunctionCallRecord,
    CreateRunRequest,
    CreateRunResponse,
    EvaluationResponse,
    EvaluationSummary,
    FunctionCallResponse,
    GradeResponse,
    RecordObservationsRequest,
    RunResponse,
)
from ..state import Evaluation, Run
from ..store import Store

router = APIRouter(prefix="/runs")


def _require_eval(evaluation: Evaluation | None, eval_id: str) -> Evaluation:
    """404 when an ID-based store mutation reports the evaluation doesn't exist."""
    if evaluation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown evaluation: {eval_id}")
    return evaluation


@router.post("", response_model=CreateRunResponse, status_code=status.HTTP_201_CREATED)
def create_run(
    req: CreateRunRequest,
    catalog: Annotated[SuiteCatalog, Depends(get_catalog)],
    store: Annotated[Store, Depends(get_store)],
):
    suite = resolve_suite(catalog, req.suite_name, req.suite_version)
    run = store.create_run(req.suite_name, suite.version)
    return CreateRunResponse(id=run.id, suite_name=run.suite_name, suite_version=run.suite_version)


@router.get("/{run_id}", response_model=RunResponse, status_code=status.HTTP_200_OK)
def retrieve_run(run: Annotated[Run, Depends(get_run)]):
    return RunResponse(
        id=run.id,
        suite_name=run.suite_name,
        suite_version=run.suite_version,
        created_at=run.created_at,
        evaluations=[
            EvaluationSummary(
                id=e.id,
                user_task_id=e.user_task_id,
                injection_task_id=e.injection_task_id,
                completed=e.completed,
                utility=e.utility,
                security=e.security,
            )
            for e in list(run.evaluations.values())
        ],
    )


@router.post("/{run_id}/evaluations", response_model=CreateEvaluationResponse, status_code=status.HTTP_201_CREATED)
def create_evaluation(
    req: CreateEvaluationRequest,
    config: Annotated[AppConfig, Depends(get_config)],
    run: Annotated[Run, Depends(get_run)],
    suite: Annotated[YAMLTaskSuite, Depends(get_run_suite)],
    store: Annotated[Store, Depends(get_store)],
):
    if req.user_task_id not in suite.user_tasks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown user task: {req.user_task_id}")
    if req.injection_task_id is not None and req.injection_task_id not in suite.injection_tasks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown injection task: {req.injection_task_id}"
        )

    environment = suite.provision_environment(req.injections)
    pre_environment = environment.model_copy(deep=True)
    prompt = suite.inject_user_task_prompt(req.user_task_id, req.injections)

    evaluation = store.create_evaluation(
        run.id,
        user_task_id=req.user_task_id,
        injection_task_id=req.injection_task_id,
        pre_environment=pre_environment,
        environment=environment,
        active_injections=req.injections,
        agent_input=prompt,
    )
    token, expires_at = store.create_session(run.id, evaluation.id, config.session_ttl_seconds)
    return CreateEvaluationResponse(id=evaluation.id, prompt=prompt, session_token=token, session_expires_at=expires_at)


@router.get(
    "/{run_id}/evaluations/{eval_id}",
    response_model=EvaluationResponse,
    status_code=status.HTTP_200_OK,
)
def retrieve_evaluation(evaluation: Annotated[Evaluation, Depends(get_evaluation_by_id)]):
    return EvaluationResponse(
        id=evaluation.id,
        user_task_id=evaluation.user_task_id,
        injection_task_id=evaluation.injection_task_id,
        completed=evaluation.completed,
        utility=evaluation.utility,
        security=evaluation.security,
        security_reason=evaluation.security_reason,
        agent_input=evaluation.agent_input,
        agent_output=evaluation.agent_output,
        function_calls=[FunctionCallResponse.model_validate(fc) for fc in evaluation.function_calls],
    )


@router.post("/{run_id}/evaluations/{eval_id}/complete", status_code=status.HTTP_200_OK)
def complete_evaluation(
    eval_id: str,
    req: CompleteRequest,
    run: Annotated[Run, Depends(get_run)],
    store: Annotated[Store, Depends(get_store)],
):
    _require_eval(store.complete_evaluation(run.id, eval_id, req.agent_output), eval_id)
    return {"status": "completed"}


@router.post("/{run_id}/evaluations/{eval_id}/grade", response_model=GradeResponse, status_code=status.HTTP_200_OK)
def grade_evaluation(
    evaluation: Annotated[Evaluation, Depends(get_evaluation_by_id)],
    suite: Annotated[YAMLTaskSuite, Depends(get_run_suite)],
    store: Annotated[Store, Depends(get_store)],
):
    if not evaluation.completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Evaluation not completed. Call complete first."
        )

    result = suite.grade(
        user_task_id=evaluation.user_task_id,
        injection_task_id=evaluation.injection_task_id,
        agent_output=evaluation.agent_output or "",
        pre_environment=evaluation.pre_environment,
        post_environment=evaluation.environment,
        function_calls=evaluation.function_calls,
        observations=evaluation.observations,
    )
    graded = GradeResponse.model_validate(result)
    store.set_grade(
        evaluation.run_id,
        evaluation.id,
        utility=graded.utility,
        security=graded.security,
        security_reason=graded.security_reason,
    )
    return graded


# --- Environment endpoints (nested under evaluation) ---


@router.get("/{run_id}/evaluations/{eval_id}/environment", status_code=status.HTTP_200_OK)
def get_environment(evaluation: Annotated[Evaluation, Depends(get_evaluation_by_id)]) -> dict:
    return evaluation.environment.model_dump()


@router.put("/{run_id}/evaluations/{eval_id}/environment")
def update_environment(
    body: dict,
    evaluation: Annotated[Evaluation, Depends(get_evaluation_by_id)],
    suite: Annotated[YAMLTaskSuite, Depends(get_run_suite)],
    store: Annotated[Store, Depends(get_store)],
) -> dict:
    env = validate_environment(suite, body)
    updated = _require_eval(store.set_environment(evaluation.run_id, evaluation.id, env), evaluation.id)
    return updated.environment.model_dump()


@router.delete("/{run_id}/evaluations/{eval_id}/session", status_code=204)
def close_session(
    evaluation: Annotated[Evaluation, Depends(get_evaluation_by_id)],
    store: Annotated[Store, Depends(get_store)],
) -> None:
    store.close_session(evaluation.run_id, evaluation.id)


# --- Function call endpoints ---


@router.get(
    "/{run_id}/evaluations/{eval_id}/function-calls",
    response_model=list[FunctionCallResponse],
    status_code=status.HTTP_200_OK,
)
def list_function_calls(evaluation: Annotated[Evaluation, Depends(get_evaluation_by_id)]) -> list[FunctionCallRecord]:
    return evaluation.function_calls


@router.get(
    "/{run_id}/evaluations/{eval_id}/function-calls/{idx}",
    response_model=FunctionCallResponse,
    status_code=status.HTTP_200_OK,
)
def get_function_call(idx: int, evaluation: Annotated[Evaluation, Depends(get_evaluation_by_id)]) -> FunctionCallRecord:
    if idx < 0 or idx >= len(evaluation.function_calls):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Function call index out of range: {idx}")
    return evaluation.function_calls[idx]


@router.post(
    "/{run_id}/evaluations/{eval_id}/function-calls",
    response_model=FunctionCallResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_function_call(
    eval_id: str,
    req: CreateFunctionCallRecord,
    run: Annotated[Run, Depends(get_run)],
    store: Annotated[Store, Depends(get_store)],
) -> FunctionCallRecord:
    evaluation = _require_eval(store.append_function_call(run.id, eval_id, req), eval_id)
    return evaluation.function_calls[-1]


# --- Observation endpoints ---
#
# Runtime evidence streams (e.g. OpenShell OCSF events) the runner reads from a
# source and records here, keyed by source — symmetric with PUT /environment.
# Verifiers read them from VerificationContext.observations at grade time.


@router.get("/{run_id}/evaluations/{eval_id}/observations", status_code=status.HTTP_200_OK)
def get_observations(evaluation: Annotated[Evaluation, Depends(get_evaluation_by_id)]) -> dict:
    return evaluation.observations


@router.post("/{run_id}/evaluations/{eval_id}/observations", status_code=status.HTTP_200_OK)
def record_observations(
    eval_id: str,
    req: RecordObservationsRequest,
    run: Annotated[Run, Depends(get_run)],
    store: Annotated[Store, Depends(get_store)],
) -> dict:
    evaluation = _require_eval(store.record_observations(run.id, eval_id, req.source, req.data), eval_id)
    return evaluation.observations
