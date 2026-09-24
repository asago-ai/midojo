from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, status

from midojo.types import SuiteName
from midojo.yaml_task_suite import YAMLTaskSuite

from ..dependencies import get_suite, get_suites
from ..models import SuiteInfoResponse

router = APIRouter(prefix="/suites")


@router.get("/{suite_name}", response_model=SuiteInfoResponse, status_code=status.HTTP_200_OK)
def suite_info(suite_name: SuiteName, suite: Annotated[YAMLTaskSuite, Depends(get_suite)]):
    return SuiteInfoResponse(
        name=suite_name,
        user_tasks=list(suite.user_tasks.keys()),
        injection_tasks=list(suite.injection_tasks.keys()),
        environment=suite.provision_environment({}),
    )


@router.get("")
def list_suites(suites: Annotated[Mapping[SuiteName, YAMLTaskSuite], Depends(get_suites)]) -> list[SuiteName]:
    return sorted(suites)
