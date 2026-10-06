"""LangChain SDK — intercepts the tools of a LangChain agent.

Lets suite authors wrap a LangChain agent's tools so they talk to the midojo
control plane for environment access and function-call recording, the same way
``midojo_sdk.mcp`` does for an MCP server.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Sequence
from typing import Any

import httpx
from langchain_core.tools import BaseTool, StructuredTool

from midojo_sdk.client import AgentControlPlaneClient
from midojo_sdk.context import ToolContext
from midojo_sdk.session import session_token

__all__ = ["MidojoToolkit", "ToolContext"]


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
    real tool of the same name from ``real_tools``.
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
                agent = AgentControlPlaneClient(self._control_plane_url, session_token(), http=self._http)
                ctx = ToolContext(agent, self._forward if self._real_tools else None)
                result: str = ""
                error: str | None = None
                try:
                    result = await fn(ctx, **kwargs)
                except Exception as e:
                    error = str(e)
                    result = error
                    raise
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

            self._tools.append(StructuredTool.from_function(coroutine=wrapper, name=fn.__name__))
            return fn

        return decorator

    def get_tools(self) -> list[BaseTool]:
        """Return the intercepted tools, to pass to a LangChain agent."""
        return list(self._tools)
