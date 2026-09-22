"""MCP SDK — Python equivalent of pi-sdk.

Lets suite authors write standalone fake MCP servers whose tools talk to the
midojo control plane for environment access and function-call recording.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any

from fastmcp import Client, FastMCP
from fastmcp.server.dependencies import get_http_headers
from mcp.types import TextContent

from midojo.control_plane_client import AgentControlPlaneClient, ControlPlaneClient
from midojo.session import SESSION_HEADER, session_token


class UpstreamClient:
    """Forwards tool calls to an upstream MCP server."""

    def __init__(self, upstream_url: str) -> None:
        self.upstream_url = upstream_url

    async def call_tool(self, name: str, args: dict) -> str:
        async with Client(self.upstream_url) as client:
            result = await client.call_tool(name, args)

        parts = []
        for content in result.content:
            if isinstance(content, TextContent):
                parts.append(content.text)
            else:
                parts.append(str(content))
        return "\n".join(parts)


class ToolContext:
    """Async access to the evaluation environment on the control plane."""

    def __init__(
        self,
        client: AgentControlPlaneClient,
        upstream: UpstreamClient | None = None,
    ) -> None:
        self._client = client
        self._upstream = upstream

    async def env(self, field: str) -> Any:
        environment = await self._client.get_environment()
        return environment[field]

    async def env_update(self, field: str, value: Any) -> None:
        environment = await self._client.get_environment()
        environment[field] = value
        await self._client.put_environment(environment)

    async def forward(self, tool_name: str, args: dict) -> str:
        """Forward a tool call to the upstream MCP server."""
        if self._upstream is None:
            raise RuntimeError(
                "No upstream MCP server configured. Pass --upstream-url when starting the fake MCP server."
            )
        return await self._upstream.call_tool(tool_name, args)


class MidojoMCP:
    """Wrapper around FastMCP that adds control plane wiring.

    Usage::

        mcp = MidojoMCP("weather", control_plane_url=...)

        @mcp.tool()
        async def get_weather(ctx: ToolContext, city: str) -> str:
            cities = await ctx.env("cities")
            ...

    The ``ctx: ToolContext`` first parameter is injected by the SDK and
    stripped from the MCP tool schema exposed to agents.
    """

    def __init__(
        self,
        name: str,
        *,
        control_plane_url: str,
        upstream_url: str | None = None,
    ) -> None:
        self._fastmcp = FastMCP(name)
        self._client = ControlPlaneClient(control_plane_url)
        self._upstream = UpstreamClient(upstream_url) if upstream_url else None

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
                incoming = get_http_headers().get(SESSION_HEADER.lower())
                token = session_token(incoming)
                agent = self._client.agent(token)
                ctx = ToolContext(agent, upstream=self._upstream)
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

            self._fastmcp.tool(wrapper, name=fn.__name__, description=fn.__doc__)
            return fn

        return decorator

    def http_app(self, path: str = "/") -> Any:
        return self._fastmcp.http_app(path=path)

    def run(self, **kwargs) -> None:
        self._fastmcp.run(**kwargs)
