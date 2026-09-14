from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from midojo.types import Environment
from midojo.yaml_task_suite import YAMLTaskSuite

from .catalog import SuiteCatalog
from .state import Evaluation, Run
from .store import Store


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_catalog(request: Request) -> SuiteCatalog:
    return request.app.state.catalog


def resolve_suite(catalog: SuiteCatalog, suite_id: str, version: str | None = None) -> YAMLTaskSuite:
    try:
        return catalog.get(suite_id, version)
    except KeyError:
        raise HTTPException(404, f"Unknown suite: {suite_id}") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def get_suite(suite_id: str, catalog: Annotated[SuiteCatalog, Depends(get_catalog)]) -> YAMLTaskSuite:
    return resolve_suite(catalog, suite_id)


def get_run(run_id: str, store: Annotated[Store, Depends(get_store)]) -> Run:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"Unknown run: {run_id}")
    return run


def get_run_suite(
    run: Annotated[Run, Depends(get_run)], catalog: Annotated[SuiteCatalog, Depends(get_catalog)]
) -> YAMLTaskSuite:
    return resolve_suite(catalog, run.suite_id, run.suite_version)


def get_evaluation_by_id(
    eval_id: str,
    run: Annotated[Run, Depends(get_run)],
    store: Annotated[Store, Depends(get_store)],
) -> Evaluation:
    evaluation = store.get_evaluation(run.id, eval_id)
    if evaluation is None:
        raise HTTPException(404, f"Unknown evaluation: {eval_id}")
    return evaluation


def get_session_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))],
) -> str:
    if credentials is None:
        raise HTTPException(401, "Evaluation session token required", headers={"WWW-Authenticate": "Bearer"})
    return credentials.credentials


def validate_environment(suite: YAMLTaskSuite, body: dict) -> Environment:
    try:
        return suite.environment_type.model_validate(body)
    except ValidationError as exc:
        errors = [{**error, "loc": ("body", *error["loc"])} for error in exc.errors()]
        raise RequestValidationError(errors) from exc
