from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from midojo.yaml_task_suite import YAMLTaskSuite

from ..dependencies import get_suite
from ..models import ToolInfoResponse

router = APIRouter()


@router.get("/tools", response_model=list[ToolInfoResponse], status_code=status.HTTP_200_OK)
def tools(suite: Annotated[YAMLTaskSuite, Depends(get_suite)]):
    return suite.get_tool_definitions()
