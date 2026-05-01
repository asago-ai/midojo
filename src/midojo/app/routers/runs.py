from __future__ import annotations

from typing import Annotated

from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.task_suite import TaskSuite
from fastapi import APIRouter, Depends, HTTPException, status

from midojo.grading import grade_task

from .. import state
from ..dependencies import get_evaluation, get_run, get_suite
from ..models import (
    CompleteRequest,
    CreateEvaluationRequest,
    CreateEvaluationResponse,
    CreateRunResponse,
    Evaluation,
    EvaluationResponse,
    EvaluationSummary,
    GradeResponse,
    Run,
    RunResponse,
    _new_id,
)

router = APIRouter(prefix="/runs")


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
    suite: Annotated[TaskSuite, Depends(get_suite)],
):
    if req.user_task_id not in suite.user_tasks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown user task: {req.user_task_id}")
    if req.injection_task_id is not None and req.injection_task_id not in suite.injection_tasks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown injection task: {req.injection_task_id}"
        )

    environment = suite.load_and_inject_default_environment(req.injections)
    pre_environment = environment.model_copy(deep=True)
    runtime = FunctionsRuntime(suite.tools)

    evaluation = Evaluation(
        id=_new_id(),
        user_task_id=req.user_task_id,
        injection_task_id=req.injection_task_id,
        pre_environment=pre_environment,
        environment=environment,
        runtime=runtime,
        active_injections=req.injections,
    )
    run.evaluations[evaluation.id] = evaluation
    state.current_eval = evaluation

    prompt = suite.user_tasks[req.user_task_id].PROMPT
    return CreateEvaluationResponse(id=evaluation.id, prompt=prompt)


@router.get("/{run_id}/evaluations/{eval_id}", response_model=EvaluationResponse, status_code=status.HTTP_200_OK)
def retrieve_evaluation(evaluation: Annotated[Evaluation, Depends(get_evaluation)]):
    return EvaluationResponse(
        id=evaluation.id,
        user_task_id=evaluation.user_task_id,
        injection_task_id=evaluation.injection_task_id,
        completed=evaluation.completed,
        utility=evaluation.utility,
        security=evaluation.security,
        model_output=evaluation.model_output,
        trace=[
            {"function": e.function, "args": e.args, "result": e.result, "error": e.error, "timestamp": e.timestamp}
            for e in evaluation.trace
        ],
    )


@router.post("/{run_id}/evaluations/{eval_id}/complete", status_code=status.HTTP_200_OK)
def complete_evaluation(req: CompleteRequest, evaluation: Annotated[Evaluation, Depends(get_evaluation)]):
    evaluation.model_output = req.model_output
    evaluation.completed = True
    return {"status": "completed"}


@router.post("/{run_id}/evaluations/{eval_id}/grade", response_model=GradeResponse, status_code=status.HTTP_200_OK)
def grade_evaluation(
    evaluation: Annotated[Evaluation, Depends(get_evaluation)],
    suite: Annotated[TaskSuite, Depends(get_suite)],
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
        trace=evaluation.trace,
    )
    evaluation.utility = result["utility"]
    evaluation.security = result["security"]
    return GradeResponse(**result)
