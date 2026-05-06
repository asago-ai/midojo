from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from midojo.yaml_task_suite import YAMLTaskSuite

from midojo.grading import grade_task

from .. import state
from ..dependencies import get_evaluation, get_run, get_suite
from ..models import (
    CompleteRequest,
    CreateEvaluationRequest,
    CreateEvaluationResponse,
    CreateRunResponse,
    EvaluationResponse,
    EvaluationSummary,
    FunctionCallRecord,
    CreateFunctionCallRecord,
    GradeResponse,
    RunResponse,
)
from ..state import Evaluation, Run, _new_id

router = APIRouter(prefix="/runs")


@router.get("/current-eval", status_code=status.HTTP_200_OK)
def get_current_eval():
    if state.current_eval is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active evaluation")
    run_id = next(
        (rid for rid, run in state.runs.items() if state.current_eval.id in run.evaluations),
        None,
    )
    return {"run_id": run_id, "eval_id": state.current_eval.id}


@router.post("", response_model=CreateRunResponse, status_code=status.HTTP_201_CREATED)
def create_run():
    run = Run(id=_new_id())
    state.runs[run.id] = run
    return CreateRunResponse(id=run.id)


@router.get("/{run_id}", response_model=RunResponse, status_code=status.HTTP_200_OK)
def retrieve_run(run: Annotated[Run, Depends(get_run)]):
    return RunResponse(
        id=run.id,
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
            for e in run.evaluations.values()
        ],
    )


@router.post("/{run_id}/evaluations", response_model=CreateEvaluationResponse, status_code=status.HTTP_201_CREATED)
def create_evaluation(
    req: CreateEvaluationRequest,
    run: Annotated[Run, Depends(get_run)],
    suite: Annotated[YAMLTaskSuite, Depends(get_suite)],
):
    if req.user_task_id not in suite.user_tasks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown user task: {req.user_task_id}")
    if req.injection_task_id is not None and req.injection_task_id not in suite.injection_tasks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown injection task: {req.injection_task_id}"
        )

    environment = suite.load_and_inject_default_environment(req.injections)
    pre_environment = environment.model_copy(deep=True)

    evaluation = Evaluation(
        id=_new_id(),
        user_task_id=req.user_task_id,
        injection_task_id=req.injection_task_id,
        pre_environment=pre_environment,
        environment=environment,
        active_injections=req.injections,
    )
    run.evaluations[evaluation.id] = evaluation
    state.current_eval = evaluation

    prompt = suite.user_tasks[req.user_task_id].PROMPT
    return CreateEvaluationResponse(id=evaluation.id, prompt=prompt)


_FC_ENV_FIELDS = {"pre_environment", "post_environment"}


@router.get(
    "/{run_id}/evaluations/{eval_id}",
    response_model=EvaluationResponse,
    response_model_exclude={"function_calls": {"__all__": _FC_ENV_FIELDS}},
    status_code=status.HTTP_200_OK,
)
def retrieve_evaluation(evaluation: Annotated[Evaluation, Depends(get_evaluation)]):
    return EvaluationResponse(
        id=evaluation.id,
        user_task_id=evaluation.user_task_id,
        injection_task_id=evaluation.injection_task_id,
        completed=evaluation.completed,
        utility=evaluation.utility,
        security=evaluation.security,
        model_output=evaluation.model_output,
        function_calls=evaluation.function_calls,
    )


@router.post("/{run_id}/evaluations/{eval_id}/complete", status_code=status.HTTP_200_OK)
def complete_evaluation(req: CompleteRequest, evaluation: Annotated[Evaluation, Depends(get_evaluation)]):
    evaluation.model_output = req.model_output
    evaluation.completed = True
    return {"status": "completed"}


@router.post("/{run_id}/evaluations/{eval_id}/grade", response_model=GradeResponse, status_code=status.HTTP_200_OK)
def grade_evaluation(
    evaluation: Annotated[Evaluation, Depends(get_evaluation)],
    suite: Annotated[YAMLTaskSuite, Depends(get_suite)],
):
    if not evaluation.completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Evaluation not completed. Call complete first."
        )

    result = grade_task(
        suite=suite,
        user_task_id=evaluation.user_task_id,
        injection_task_id=evaluation.injection_task_id,
        model_output=evaluation.model_output or "",
        pre_environment=evaluation.pre_environment,
        post_environment=evaluation.environment,
        function_calls=evaluation.function_calls,
    )
    evaluation.utility = result["utility"]
    evaluation.security = result["security"]
    return GradeResponse(**result)


# --- Environment endpoints (nested under evaluation) ---


@router.get("/{run_id}/evaluations/{eval_id}/environment", status_code=status.HTTP_200_OK)
def get_environment(evaluation: Annotated[Evaluation, Depends(get_evaluation)]) -> dict:
    return evaluation.environment.model_dump()


def register_environment_update_route(env_type: type) -> None:
    def update_environment(body, evaluation: Annotated[Evaluation, Depends(get_evaluation)]) -> dict:
        evaluation.environment = body
        return evaluation.environment.model_dump()

    update_environment.__annotations__["body"] = env_type
    router.add_api_route(
        "/{run_id}/evaluations/{eval_id}/environment", update_environment, methods=["PUT"]
    )


# --- Function call endpoints ---


@router.get(
    "/{run_id}/evaluations/{eval_id}/function-calls",
    response_model=list[FunctionCallRecord],
    response_model_exclude={"__all__": _FC_ENV_FIELDS},
    status_code=status.HTTP_200_OK,
)
def list_function_calls(evaluation: Annotated[Evaluation, Depends(get_evaluation)]) -> list[FunctionCallRecord]:
    return evaluation.function_calls


@router.get(
    "/{run_id}/evaluations/{eval_id}/function-calls/{idx}",
    response_model=FunctionCallRecord,
    status_code=status.HTTP_200_OK,
)
def get_function_call(idx: int, evaluation: Annotated[Evaluation, Depends(get_evaluation)]) -> FunctionCallRecord:
    if idx < 0 or idx >= len(evaluation.function_calls):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Function call index out of range: {idx}")
    return evaluation.function_calls[idx]


@router.post(
    "/{run_id}/evaluations/{eval_id}/function-calls",
    response_model=FunctionCallRecord,
    status_code=status.HTTP_201_CREATED,
)
def record_function_call(
    req: CreateFunctionCallRecord,
    evaluation: Annotated[Evaluation, Depends(get_evaluation)],
) -> FunctionCallRecord:
    if evaluation.function_calls:
        pre_env = evaluation.function_calls[-1].post_environment
    else:
        pre_env = evaluation.pre_environment
    record = FunctionCallRecord(
        **req.model_dump(),
        timestamp=datetime.now(timezone.utc).isoformat(),
        pre_environment=pre_env,
        post_environment=evaluation.environment.model_copy(deep=True),
    )
    evaluation.function_calls.append(record)
    return record
