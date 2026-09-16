from __future__ import annotations

from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter

from midojo.types import SuiteName
from midojo.yaml_task_suite import YAMLTaskSuite

from .config import AppConfig
from .routers import agent, runs, suite, tasks
from .store import InMemoryStore, InvalidSessionError, Store

_SUITE_NAME = TypeAdapter(SuiteName)


def create_app(
    suites: Mapping[SuiteName, YAMLTaskSuite],
    *,
    store: Store | None = None,
    config: AppConfig | None = None,
) -> FastAPI:
    app = FastAPI()
    app.state.suites = {_SUITE_NAME.validate_python(name): suite for name, suite in suites.items()}
    app.state.store = store if store is not None else InMemoryStore()
    app.state.config = config if config is not None else AppConfig()
    app.include_router(suite.router)
    app.include_router(tasks.router)
    app.include_router(runs.router)
    app.include_router(agent.router)

    @app.exception_handler(InvalidSessionError)
    async def invalid_session(request: Request, exc: InvalidSessionError) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": str(exc)}, headers={"WWW-Authenticate": "Bearer"})

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app
