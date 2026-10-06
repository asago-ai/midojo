"""LangChain SDK — intercepts the tool calls of a LangChain agent.

Lets suite authors hook, block and report the tools of a LangChain agent, with
access to the midojo control plane, the same way ``@midojo/pi-sdk`` does for a
PI agent.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command

from midojo_sdk.client import AgentControlPlaneClient
from midojo_sdk.context import ToolContext
from midojo_sdk.session import session_token

__all__ = ["BLOCKED_REASON", "MidojoMiddleware", "ToolContext"]

BLOCKED_REASON = "Tool execution was blocked"
"""What the agent is told when it calls a blocked tool, the same as with the PI SDK."""

Hook = Callable[[ToolContext, dict[str, Any], str], Awaitable[str]]
Handler = Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]
_Intercept = Callable[[ToolCallRequest, Handler], Awaitable[ToolMessage | Command]]


class MidojoMiddleware(AgentMiddleware):
    """Intercepts an agent's tool calls by tool name, with control plane wiring.

    Usage::

        midojo = MidojoMiddleware(control_plane_url=...)

        @midojo.hook("get_weather")
        async def inject_note(ctx: ToolContext, args: dict[str, Any], real_result: str) -> str:
            return real_result + await ctx.env("injected_note")

        midojo.block("send_email")
        midojo.report("read_file")

        agent = create_agent(model, tools=[get_weather, send_email, read_file], middleware=[midojo])

    The agent keeps its real tools, so it sees the same tool names,
    descriptions and arguments as without midojo. Tools that aren't hooked,
    blocked or reported run as usual and aren't recorded. For a LangGraph
    ``ToolNode``, pass ``awrap_tool_call=midojo.awrap_tool_call`` instead.

    Interception is asynchronous, so run the agent with ``ainvoke`` or
    ``astream``.
    """

    def __init__(self, *, control_plane_url: str, http: httpx.AsyncClient | None = None) -> None:
        super().__init__()
        self._control_plane_url = control_plane_url
        self._http = http or httpx.AsyncClient(timeout=300.0)
        self._intercepts: dict[str, _Intercept] = {}

    def hook(self, tool_name: str) -> Callable[[Hook], Hook]:
        """Rewrite what the tool named ``tool_name`` returns to the agent.

        The decorated function takes ``(ctx, args, real_result)``: the real tool
        runs first, and the function's return value is what the agent gets. The
        call is recorded with the rewritten result. When the function raises,
        the call is recorded with its error and the agent gets the error message
        as an error result, so the agent run goes on.
        """

        def decorator(fn: Hook) -> Hook:
            async def intercept(request: ToolCallRequest, handler: Handler) -> ToolMessage | Command:
                agent = self._agent()
                args = request.tool_call["args"]
                output = await _run(agent, request, handler)
                if not isinstance(output, ToolMessage):
                    raise TypeError(f"Cannot hook {tool_name}: it returned a {type(output).__name__}, not a message.")
                try:
                    result = await fn(ToolContext(agent), args, output.text)
                except Exception as e:
                    await agent.record_function_call(function=tool_name, args=args, result=str(e), error=str(e))
                    return _error(request, str(e))
                await agent.record_function_call(function=tool_name, args=args, result=result)
                return output.model_copy(update={"content": result})

            self._add(tool_name, intercept)
            return fn

        return decorator

    def block(self, *tool_names: str) -> None:
        """Block the tools named ``tool_names``: the agent still sees them, but they never run.

        When the agent calls a blocked tool, the call is recorded as blocked and
        the agent gets ``BLOCKED_REASON`` as an error result. Use this for a
        tool whose effect must not happen during an evaluation, such as sending
        email, while still recording that the agent attempted it.
        """

        async def intercept(request: ToolCallRequest, handler: Handler) -> ToolMessage:
            await self._agent().record_function_call(
                function=request.tool_call["name"],
                args=request.tool_call["args"],
                result=BLOCKED_REASON,
                blocked=True,
            )
            return _error(request, BLOCKED_REASON)

        for tool_name in tool_names:
            self._add(tool_name, intercept)

    def report(self, *tool_names: str) -> None:
        """Record every call to the tools named ``tool_names`` without changing what the agent sees.

        Each tool runs as before and the agent gets its real output, while the
        call and its result are recorded on the control plane. Use this to make
        a tool's result, such as a file read, visible to midojo without
        perturbing the agent.
        """

        async def intercept(request: ToolCallRequest, handler: Handler) -> ToolMessage | Command:
            agent = self._agent()
            output = await _run(agent, request, handler)
            result = output.text if isinstance(output, ToolMessage) else str(output)
            error = result if isinstance(output, ToolMessage) and output.status == "error" else None
            await agent.record_function_call(
                function=request.tool_call["name"], args=request.tool_call["args"], result=result, error=error
            )
            return output

        for tool_name in tool_names:
            self._add(tool_name, intercept)

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Handler) -> ToolMessage | Command:
        intercept = self._intercepts.get(request.tool_call["name"])
        if intercept is None:
            return await handler(request)
        return await intercept(request, handler)

    def _add(self, tool_name: str, intercept: _Intercept) -> None:
        if tool_name in self._intercepts:
            raise ValueError(f"{tool_name} is already intercepted.")
        self._intercepts[tool_name] = intercept

    def _agent(self) -> AgentControlPlaneClient:
        return AgentControlPlaneClient(self._control_plane_url, session_token(), http=self._http)


async def _run(agent: AgentControlPlaneClient, request: ToolCallRequest, handler: Handler) -> ToolMessage | Command:
    """Run the real tool, recording the call if it raises."""
    try:
        return await handler(request)
    except GraphBubbleUp:
        raise
    except Exception as e:
        await agent.record_function_call(
            function=request.tool_call["name"], args=request.tool_call["args"], result=str(e), error=str(e)
        )
        raise


def _error(request: ToolCallRequest, message: str) -> ToolMessage:
    return ToolMessage(
        content=message, name=request.tool_call["name"], tool_call_id=request.tool_call["id"], status="error"
    )
