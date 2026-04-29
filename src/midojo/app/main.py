from __future__ import annotations

from types import ModuleType

from agentdojo.task_suite.task_suite import TaskSuite
from fastapi import FastAPI

from midojo.app.models import SessionHolder
from midojo.app.routers.admin import create_admin_router
from midojo.app.routers.mcp import create_mcp_server
from midojo.app.routers.tasks import create_task_router


def create_app(
    suite: TaskSuite,
    suite_module: ModuleType,
) -> FastAPI:
    session_holder = SessionHolder()

    mcp_server = create_mcp_server(suite.tools, session_holder)
    mcp_app = mcp_server.http_app(path="/")

    task_router = create_task_router(session_holder, suite, suite_module)
    admin_router = create_admin_router(suite, suite_module)

    app = FastAPI(lifespan=mcp_app.router.lifespan_context)
    app.include_router(task_router)
    app.include_router(admin_router)
    app.mount("/mcp", mcp_app)
    return app
