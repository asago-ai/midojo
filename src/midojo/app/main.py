from __future__ import annotations

from agentdojo.task_suite.task_suite import TaskSuite
from fastapi import FastAPI

from . import state
from .routers import environment, runs, suite, tasks, tools
from .routers.mcp import create_mcp_server


def create_app(suite_instance: TaskSuite) -> FastAPI:
    state.suite = suite_instance
    state.runs = {}
    state.current_eval = None

    mcp_server = create_mcp_server(suite_instance.tools)
    mcp_app = mcp_server.http_app(path="/")

    app = FastAPI(lifespan=mcp_app.router.lifespan_context)
    app.include_router(suite.router)
    app.include_router(tasks.router)
    # registered here because the concrete environment Pydantic type is only available after suite init
    environment.register_update_route(suite_instance.environment_type)
    app.include_router(environment.router)
    app.include_router(tools.router)
    app.include_router(runs.router)
    app.mount("/mcp", mcp_app)
    return app
