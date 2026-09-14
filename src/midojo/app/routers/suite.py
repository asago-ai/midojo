from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from midojo.yaml_task_suite import YAMLTaskSuite

from ..catalog import SuiteCatalog
from ..dependencies import get_catalog, get_suite
from ..models import SuiteInfoResponse

router = APIRouter(prefix="/suites")


@router.get("/{suite_id}", response_model=SuiteInfoResponse, status_code=status.HTTP_200_OK)
def suite_info(suite_id: str, suite: Annotated[YAMLTaskSuite, Depends(get_suite)]):
    return SuiteInfoResponse(
        id=suite_id,
        version=suite.version,
        user_tasks=list(suite.user_tasks.keys()),
        injection_tasks=list(suite.injection_tasks.keys()),
        environment=suite.provision_environment({}),
    )


@router.get("")
def list_suites(catalog: Annotated[SuiteCatalog, Depends(get_catalog)]) -> list[str]:
    return catalog.list_ids()
