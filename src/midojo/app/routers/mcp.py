from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone

from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
from agentdojo.functions_runtime import Function
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from midojo.forwarding import MCPForwardingClient

from .. import state
from ..models import FunctionCallRecord


def _make_tool_handler(func: Function):
    fields = func.parameters.model_fields

    async def handler(**kwargs):
        evaluation = state.current_eval
        if evaluation is None:
            raise ToolError("No evaluation in progress. Create one via POST /runs/{run_id}/evaluations first.")

        pre_env = evaluation.environment.model_copy(deep=True)

        if MCPForwardingClient.is_initialized():
            result, error = await asyncio.to_thread(
                evaluation.runtime.run_function, evaluation.environment, func.name, kwargs
            )
        else:
            result, error = evaluation.runtime.run_function(evaluation.environment, func.name, kwargs)

        result_str = tool_result_to_str(result) if result is not None else ""
        post_env = evaluation.environment.model_copy(deep=True)

        evaluation.function_calls.append(
            FunctionCallRecord(
                function=func.name,
                args=dict(kwargs),
                result=result_str,
                error=error,
                timestamp=datetime.now(timezone.utc).isoformat(),
                pre_environment=pre_env,
                post_environment=post_env,
            )
        )
        if error:
            raise ToolError(error)
        return result_str

    params = []
    for name, f in fields.items():
        default = inspect.Parameter.empty if f.is_required() else f.default
        params.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=f.annotation,
            )
        )
    handler.__signature__ = inspect.Signature(params)
    handler.__annotations__ = {name: f.annotation for name, f in fields.items()}
    handler.__name__ = func.name
    handler.__doc__ = func.description
    return handler


def create_mcp_server(tools: list[Function]) -> FastMCP:
    mcp = FastMCP("midojo-benchmark")

    for func in tools:
        tool_handler = _make_tool_handler(func)
        mcp.tool(tool_handler, name=func.name, description=func.description)

    return mcp
