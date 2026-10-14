"""MCP SDK — Python equivalent of the PI SDK.

Lets suite authors write standalone fake MCP servers whose tools talk to the
midojo control plane for environment access and function-call recording.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import sys
from typing import Any

import httpx
from fastmcp import Client, FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult
from mcp.types import CallToolRequestParams, TextContent
from pydantic import BaseModel

from midojo_sdk.client import AgentControlPlaneClient
from midojo_sdk.context import ToolContext
from midojo_sdk.session import SESSION_HEADER, session_token

__all__ = ["MidojoMCP", "RequestLoggingMiddleware", "ToolContext", "UpstreamClient"]

_LOGGER = logging.getLogger("midojo_sdk.mcp")

_CLIP_LENGTH = 2000


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


def _clip(text: str, limit: int = _CLIP_LENGTH) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _summarize(message: Any) -> str:
    """Compact JSON rendering of a JSON-RPC params object, for logging."""
    try:
        if isinstance(message, BaseModel):
            return _clip(message.model_dump_json(exclude_none=True))
        return _clip(json.dumps(message, default=str))
    except (TypeError, ValueError):
        return _clip(repr(message))


def _ensure_stdout_handler() -> None:
    """Emit request logs even when the host process configures no logging."""
    if _LOGGER.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [midojo-sdk] %(message)s"))
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False


class RequestLoggingMiddleware(Middleware):
    """Log the MCP conversation: every request with its params, every tool
    call with its arguments and its result (or error).

    Fake MCP servers usually run with stdout redirected to a log file the suite
    copies out of the sandbox (the helpdesk suite's ``/tmp/fake_mcp.log``),
    which otherwise holds only uvicorn access lines. This middleware turns
    that file into a transcript of what the agent asked and what it got back,
    alongside — not instead of — the function-call recording on the control
    plane.
    """

    async def on_message(self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]) -> Any:
        # tools/call is logged with its result by on_call_tool; skip it here.
        if context.source == "client" and context.method != "tools/call":
            _LOGGER.info("-> %s %s", context.method, _summarize(context.message))
        return await call_next(context)

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        params = context.message
        _LOGGER.info("-> tools/call %s %s", params.name, _clip(json.dumps(params.arguments or {})))
        try:
            result = await call_next(context)
        except Exception as e:
            _LOGGER.info("<- tools/call %s error: %s", params.name, e)
            raise
        text = "\n".join(block.text if isinstance(block, TextContent) else repr(block) for block in result.content)
        _LOGGER.info("<- tools/call %s %s", params.name, _clip(text))
        return result


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

    ``log_requests`` (default) logs every JSON-RPC message and tool result to
    stdout via :class:`RequestLoggingMiddleware`.
    """

    def __init__(
        self,
        name: str,
        *,
        control_plane_url: str,
        upstream_url: str | None = None,
        http: httpx.AsyncClient | None = None,
        log_requests: bool = True,
    ) -> None:
        self._fastmcp = FastMCP(name)
        self._control_plane_url = control_plane_url
        self._http = http or httpx.AsyncClient(timeout=300.0)
        self._upstream = UpstreamClient(upstream_url) if upstream_url else None
        if log_requests:
            _ensure_stdout_handler()
            self._fastmcp.add_middleware(RequestLoggingMiddleware())

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
                agent = AgentControlPlaneClient(self._control_plane_url, token, http=self._http)
                ctx = ToolContext(agent, self._upstream.call_tool if self._upstream else None)
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
