"""Tests for MCP tool registration and forwarding independent of the control plane."""

import asyncio

import pytest

from midojo.control_plane_client import ControlPlaneClient
from midojo.mcp_sdk import MidojoMCP, ToolContext


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
    ctx = ToolContext(ControlPlaneClient("http://localhost:9999"), "unused")
    with pytest.raises(RuntimeError, match="No upstream MCP server configured"):
        await ctx.forward("get_weather", {"city": "New York"})
