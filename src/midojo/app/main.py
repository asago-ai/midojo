from __future__ import annotations

from collections.abc import Mapping, Sequence

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from midojo.yaml_task_suite import YAMLTaskSuite

from .catalog import SuiteCatalog
from .config import AppConfig
from .routers import agent, runs, suite, tasks
from .store import InMemoryStore, InvalidSessionError, Store


def create_app(
    suites: Mapping[str, YAMLTaskSuite] | Sequence[str],
    *,
    store: Store | None = None,
    config: AppConfig | None = None,
) -> FastAPI:
    app = FastAPI()
    app.state.catalog = SuiteCatalog(suites)
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
