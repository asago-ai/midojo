from __future__ import annotations

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class MCPForwardingClient:
    """Forwards tool calls to an upstream MCP server."""

    _instance: MCPForwardingClient | None = None

    def __init__(self, upstream_url: str) -> None:
        self.upstream_url = upstream_url

    @classmethod
    def initialize(cls, upstream_url: str) -> MCPForwardingClient:
        cls._instance = cls(upstream_url)
        return cls._instance

    @classmethod
    def get_instance(cls) -> MCPForwardingClient:
        if cls._instance is None:
            raise RuntimeError("ForwardingClient not initialized. Pass --real-mcp-url at startup.")
        return cls._instance

    @classmethod
    def is_initialized(cls) -> bool:
        return cls._instance is not None

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None

    def call_tool(self, name: str, args: dict) -> str:
        """Forward a tool call synchronously. Uses asyncio.run() internally."""
        return asyncio.run(self._async_call_tool(name, args))

    async def _async_call_tool(self, name: str, args: dict) -> str:
        async with streamablehttp_client(self.upstream_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, args)

        parts = []
        for content in result.content:
            if hasattr(content, "text"):
                parts.append(content.text)
            else:
                parts.append(str(content))
        return "\n".join(parts)
