from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from midojo.yaml_task_suite import YAMLTaskSuite

from ..dependencies import get_suite
from ..models import (
    InjectionVectorInfo,
    SuiteInfoResponse,
)

router = APIRouter(prefix="/suite")


@router.get("", response_model=SuiteInfoResponse, status_code=status.HTTP_200_OK)
def suite_info(suite: Annotated[YAMLTaskSuite, Depends(get_suite)]):
    return SuiteInfoResponse(
        user_tasks=list(suite.user_tasks.keys()),
        injection_tasks=list(suite.injection_tasks.keys()),
        tools=suite.get_tool_names(),
        injection_vectors=suite.get_injection_vector_info(),
        environment=suite.load_and_inject_default_environment({}),
    )


@router.get("/injection-vectors", status_code=status.HTTP_200_OK)
def injection_vectors(suite: Annotated[YAMLTaskSuite, Depends(get_suite)]) -> dict[str, InjectionVectorInfo]:
    return suite.get_injection_vector_info()


