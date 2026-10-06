"""LangChain SDK — intercepts the tools of a LangChain agent.

Lets suite authors wrap a LangChain agent's tools so they talk to the midojo
control plane for environment access and function-call recording, the same way
``midojo_sdk.mcp`` does for an MCP server.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Sequence
from typing import Any

import httpx
from langchain_core.messages import ToolCall, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool, ToolException

from midojo_sdk.client import AgentControlPlaneClient
from midojo_sdk.context import ToolContext
from midojo_sdk.session import session_token

__all__ = ["BLOCKED_REASON", "MidojoToolkit", "ToolContext"]

BLOCKED_REASON = "Tool execution was blocked"
"""What the agent is told when it calls a blocked tool, the same as with the PI SDK."""


class MidojoToolkit:
    """Builds LangChain tools with control plane wiring.

    Usage::

        toolkit = MidojoToolkit(control_plane_url=..., real_tools=[get_weather])

        @toolkit.tool()
        async def get_weather(ctx: ToolContext, city: str) -> str:
            \"\"\"Get the weather for a city.\"\"\"
            real = await ctx.forward("get_weather", {"city": city})
            return real + await ctx.env("injected_note")

        agent = create_agent(model, tools=toolkit.get_tools())

    The ``ctx: ToolContext`` first parameter is injected by the SDK and
    stripped from the tool schema exposed to agents. ``ctx.forward`` calls the
    real tool of the same name from ``real_tools``. When a tool raises, the
    call is recorded with its error and the agent gets the error message as
    the tool's result, so the agent run goes on.
    """

    def __init__(
        self,
        *,
        control_plane_url: str,
        real_tools: Sequence[BaseTool] = (),
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._control_plane_url = control_plane_url
        self._http = http or httpx.AsyncClient(timeout=300.0)
        self._real_tools = {tool.name: tool for tool in real_tools}
        self._tools: list[BaseTool] = []

    def _agent(self) -> AgentControlPlaneClient:
        return AgentControlPlaneClient(self._control_plane_url, session_token(), http=self._http)

    def _add(self, tool: BaseTool) -> None:
        if any(existing.name == tool.name for existing in self._tools):
            raise ValueError(f"The toolkit already has a tool named {tool.name}.")
        self._tools.append(tool)

    async def _forward(self, tool_name: str, args: dict[str, Any]) -> str:
        real_tool = self._real_tools.get(tool_name)
        if real_tool is None:
            raise RuntimeError(f"Cannot forward {tool_name}: no real tool has that name.")
        return str(await real_tool.ainvoke(args))

    def tool(self):
        def decorator(fn):
            sig = inspect.signature(fn, eval_str=True)
            params = list(sig.parameters.values())
            if not params or params[0].annotation is not ToolContext:
                raise TypeError(f"First parameter of {fn.__name__} must be annotated as ToolContext")
            user_params = params[1:]
            user_sig = sig.replace(parameters=user_params)

            @functools.wraps(fn)
            async def wrapper(**kwargs):
                agent = self._agent()
                ctx = ToolContext(agent, self._forward if self._real_tools else None)
                result: str = ""
                error: str | None = None
                try:
                    result = await fn(ctx, **kwargs)
                except Exception as e:
                    error = str(e)
                    result = error
                    raise ToolException(error) from e
                finally:
                    await agent.record_function_call(
                        function=fn.__name__,
                        args=kwargs,
                        result=result,
                        error=error,
                    )
                return result

            setattr(wrapper, "__signature__", user_sig)
            wrapper.__annotations__ = {
                p.name: p.annotation for p in user_params if p.annotation is not inspect.Parameter.empty
            }

            self._add(StructuredTool.from_function(coroutine=wrapper, name=fn.__name__, handle_tool_error=True))
            return fn

        return decorator

    def block(self, *tools: BaseTool) -> None:
        """Block ``tools``: the agent still sees them, but they never run.

        When the agent calls a blocked tool, the call is recorded as blocked and
        the agent gets ``BLOCKED_REASON`` as an error result. Use this for a
        tool whose effect must not happen during an evaluation, such as sending
        email, while still recording that the agent attempted it.
        """
        for real_tool in tools:
            self._add(self._blocked(real_tool))

    def _blocked(self, real_tool: BaseTool) -> BaseTool:
        async def blocked(**kwargs: Any) -> str:
            await self._agent().record_function_call(
                function=real_tool.name, args=kwargs, result=BLOCKED_REASON, blocked=True
            )
            raise ToolException(BLOCKED_REASON)

        return _like(real_tool, blocked, handle_tool_error=True)

    def report(self, *tools: BaseTool) -> None:
        """Record every call to ``tools`` without changing what the agent sees.

        Each tool runs as before and the agent gets its real output, while the
        call and its result are recorded on the control plane. Use this to make
        a tool's result, such as a file read, visible to midojo without
        perturbing the agent.
        """
        for real_tool in tools:
            self._add(_ReportedTool(real_tool, self._agent))

    def get_tools(self) -> list[BaseTool]:
        """Return the intercepted tools, to pass to a LangChain agent."""
        return list(self._tools)


def _like(real_tool: BaseTool, coroutine: Any, **kwargs: Any) -> StructuredTool:
    """Build a tool that the agent sees as ``real_tool``, running ``coroutine`` instead."""
    args_schema = real_tool.args_schema if real_tool.args_schema is not None else real_tool.get_input_schema()
    return StructuredTool(
        name=real_tool.name,
        description=real_tool.description,
        args_schema=args_schema,
        coroutine=coroutine,
        return_direct=real_tool.return_direct,
        **kwargs,
    )


class _ReportedTool(BaseTool):
    """Runs a real tool unchanged and records each call with its result."""

    _real_tool: BaseTool
    _new_agent: Callable[[], AgentControlPlaneClient]

    def __init__(self, real_tool: BaseTool, new_agent: Callable[[], AgentControlPlaneClient]) -> None:
        super().__init__(
            name=real_tool.name,
            description=real_tool.description,
            args_schema=real_tool.args_schema,
            return_direct=real_tool.return_direct,
        )
        self._real_tool = real_tool
        self._new_agent = new_agent

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Reported tools only run asynchronously.")

    async def ainvoke(
        self, input: str | dict[str, Any] | ToolCall, config: RunnableConfig | None = None, **kwargs: Any
    ) -> Any:
        agent = self._new_agent()
        args = input["args"] if isinstance(input, dict) and input.get("type") == "tool_call" else input
        args = dict(args) if isinstance(args, dict) else {"input": args}
        try:
            output = await self._real_tool.ainvoke(input, config, **kwargs)
        except Exception as e:
            await agent.record_function_call(function=self.name, args=args, result=str(e), error=str(e))
            raise
        result = output.text if isinstance(output, ToolMessage) else str(output)
        error = result if isinstance(output, ToolMessage) and output.status == "error" else None
        await agent.record_function_call(function=self.name, args=args, result=result, error=error)
        return output
