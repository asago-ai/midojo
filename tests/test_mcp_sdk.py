"""Tests for MCP tool registration and forwarding independent of the control plane."""

import asyncio
import logging

import httpx
import pytest
from fastmcp import Client
from midojo_sdk.client import AgentControlPlaneClient
from midojo_sdk.mcp import MidojoMCP, ToolContext


class _ListHandler(logging.Handler):
    """Captures log records as formatted messages for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def test_midojo_mcp_tool_registration():
    mcp = MidojoMCP("test", control_plane_url="http://localhost:9999")

    @mcp.tool()
    async def my_tool(ctx: ToolContext, name: str) -> str:
        """A test tool."""
        return f"hello {name}"

    tools = asyncio.run(mcp._fastmcp.list_tools())
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "my_tool"
    assert "name" in tool.parameters.get("properties", {})
    assert "ctx" not in tool.parameters.get("properties", {})


def test_midojo_mcp_tool_requires_ctx():
    mcp = MidojoMCP("test", control_plane_url="http://localhost:9999")

    with pytest.raises(TypeError, match="ToolContext"):

        @mcp.tool()
        async def bad_tool(name: str) -> str:
            """Missing ctx."""
            return name


@pytest.mark.asyncio
async def test_tool_context_forward_raises_without_upstream():
    async with httpx.AsyncClient() as http:
        ctx = ToolContext(AgentControlPlaneClient("http://localhost:9999", "unused", http=http))
        with pytest.raises(RuntimeError, match="no upstream is configured"):
            await ctx.forward("get_weather", {"city": "New York"})


def _mock_control_plane() -> httpx.AsyncClient:
    """An httpx client whose POSTs to the control plane always succeed."""
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))


@pytest.mark.asyncio
async def test_request_logging_records_tool_traffic(monkeypatch):
    monkeypatch.setenv("MIDOJO_SESSION_TOKEN", "test-session")
    capture = _ListHandler()
    log = logging.getLogger("midojo_sdk.mcp")
    log.addHandler(capture)
    try:
        mcp = MidojoMCP("test", control_plane_url="http://control-plane.invalid", http=_mock_control_plane())

        @mcp.tool()
        async def greet(ctx: ToolContext, who: str) -> str:
            """Greet someone."""
            return f"hello {who}"

        async with Client(mcp._fastmcp) as client:
            await client.call_tool("greet", {"who": "world"})
    finally:
        log.removeHandler(capture)

    lines = "\n".join(capture.lines)
    assert "-> tools/list" in lines
    assert '-> tools/call greet {"who": "world"}' in lines
    assert "<- tools/call greet hello world" in lines


@pytest.mark.asyncio
async def test_request_logging_can_be_disabled(monkeypatch):
    monkeypatch.setenv("MIDOJO_SESSION_TOKEN", "test-session")
    capture = _ListHandler()
    log = logging.getLogger("midojo_sdk.mcp")
    log.addHandler(capture)
    try:
        mcp = MidojoMCP(
            "test", control_plane_url="http://control-plane.invalid", http=_mock_control_plane(), log_requests=False
        )

        @mcp.tool()
        async def greet(ctx: ToolContext, who: str) -> str:
            """Greet someone."""
            return f"hello {who}"

        async with Client(mcp._fastmcp) as client:
            await client.call_tool("greet", {"who": "world"})
    finally:
        log.removeHandler(capture)

    assert capture.lines == []
