from __future__ import annotations

from types import ModuleType

from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.task_suite import TaskSuite
from fastapi import APIRouter, HTTPException, status

from midojo.app.models import (
    BenchmarkSession,
    CompleteRequest,
    GradeResponse,
    SessionHolder,
    SetupRequest,
    SetupResponse,
    StatusResponse,
    TraceResponse,
)
from midojo.grading import grade_task


def create_task_router(session_holder: SessionHolder, suite: TaskSuite, suite_module: ModuleType) -> APIRouter:

    router = APIRouter()

    @router.post("/task/setup", response_model=SetupResponse, status_code=status.HTTP_201_CREATED)
    def setup_task(req: SetupRequest):
        if req.user_task_id not in suite.user_tasks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown user task: {req.user_task_id}"
            )
        if req.injection_task_id is not None and req.injection_task_id not in suite.injection_tasks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown injection task: {req.injection_task_id}"
            )

        environment = suite.load_and_inject_default_environment(req.injections)
        pre_environment = environment.model_copy(deep=True)
        runtime = FunctionsRuntime(suite.tools)

        session_holder.session = BenchmarkSession(
            user_task_id=req.user_task_id,
            injection_task_id=req.injection_task_id,
            pre_environment=pre_environment,
            environment=environment,
            runtime=runtime,
            active_injections=req.injections,
        )

        return SetupResponse(
            status="ready",
            user_task_id=req.user_task_id,
            injection_task_id=req.injection_task_id,
        )

    @router.get("/task/status", response_model=StatusResponse, status_code=status.HTTP_200_OK)
    def task_status():
        session = session_holder.session
        if session is None:
            return StatusResponse(user_task_id=None, injection_task_id=None, tool_calls_count=0, completed=False)
        return StatusResponse(
            user_task_id=session.user_task_id,
            injection_task_id=session.injection_task_id,
            tool_calls_count=len(session.trace),
            completed=session.completed,
        )

    @router.post("/task/complete", status_code=status.HTTP_200_OK)
    def complete_task(req: CompleteRequest):
        session = session_holder.session
        if session is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No task configured.")
        session.model_output = req.model_output
        session.completed = True
        return {"status": "completed"}

    @router.get("/task/trace", response_model=TraceResponse, status_code=status.HTTP_200_OK)
    def get_trace():
        session = session_holder.session
        if session is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No task configured.")
        return TraceResponse(
            trace=[
                {"function": e.function, "args": e.args, "result": e.result, "error": e.error, "timestamp": e.timestamp}
                for e in session.trace
            ]
        )

    @router.post("/task/grade", response_model=GradeResponse, status_code=status.HTTP_200_OK)
    def grade():
        session = session_holder.session
        if session is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No task configured.")
        if not session.completed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Task not completed. Call /task/complete first."
            )

        result = grade_task(
            suite=suite,
            user_task_id=session.user_task_id,
            injection_task_id=session.injection_task_id,
            model_output=session.model_output or "",
            pre_environment=session.pre_environment,
            post_environment=session.environment,
            trace=session.trace,
        )
        return GradeResponse(**result)

    @router.get("/task/prompt", status_code=status.HTTP_200_OK)
    def get_prompt():
        session = session_holder.session
        if session is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No task configured.")
        user_task = suite.user_tasks[session.user_task_id]
        return {"prompt": user_task.PROMPT}

    return router
