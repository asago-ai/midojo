from __future__ import annotations

from fastapi import HTTPException, status

from midojo.yaml_task_suite import YAMLTaskSuite

from . import state
from .models import Evaluation, Run


def get_suite() -> YAMLTaskSuite:
    return state.suite


def get_run(run_id: str) -> Run:
    run = state.runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown run: {run_id}")
    return run


def get_evaluation(run_id: str, eval_id: str) -> Evaluation:
    run = get_run(run_id)
    evaluation = run.evaluations.get(eval_id)
    if evaluation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown evaluation: {eval_id}")
    return evaluation
