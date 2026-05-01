from __future__ import annotations

from typing import Annotated

import yaml
from agentdojo.task_suite.task_suite import InjectionVector, TaskSuite, read_suite_file
from fastapi import APIRouter, Depends, status

from ..dependencies import get_suite
from ..models import (
    CheckResponse,
    InjectionTaskCheckResult,
    InjectionVectorInfo,
    SuiteInfoResponse,
    UserTaskCheckResult,
)

router = APIRouter(prefix="/suite")


def _get_injection_vectors(suite: TaskSuite) -> dict[str, InjectionVector]:
    text = read_suite_file(suite.name, "injection_vectors.yaml", suite.data_path)
    raw = yaml.safe_load(text)
    return {vid: InjectionVector.model_validate(vinfo) for vid, vinfo in raw.items()}


@router.get("", response_model=SuiteInfoResponse, status_code=status.HTTP_200_OK)
def suite_info(suite: Annotated[TaskSuite, Depends(get_suite)]):
    vectors = _get_injection_vectors(suite)
    return SuiteInfoResponse(
        user_tasks=list(suite.user_tasks.keys()),
        injection_tasks=list(suite.injection_tasks.keys()),
        tools=[t.name for t in suite.tools],
        injection_vectors={
            vid: InjectionVectorInfo(description=v.description, default=v.default) for vid, v in vectors.items()
        },
    )


@router.get("/check", response_model=CheckResponse, status_code=status.HTTP_200_OK)
def check(suite: Annotated[TaskSuite, Depends(get_suite)]):
    passed, (user_results, injection_results) = suite.check(check_injectable=False)
    return CheckResponse(
        passed=passed,
        user_tasks={tid: UserTaskCheckResult(passed=ok, message=msg) for tid, (ok, msg) in user_results.items()},
        injection_tasks={tid: InjectionTaskCheckResult(passed=ok) for tid, ok in injection_results.items()},
    )
