"""The context an intercepted tool receives."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from midojo_sdk.client import AgentControlPlaneClient

Forward = Callable[[str, dict[str, Any]], Awaitable[str]]


class ToolContext:
    """Async access to the evaluation environment on the control plane, and to the real tool."""

    def __init__(self, client: AgentControlPlaneClient, forward: Forward | None = None) -> None:
        self._client = client
        self._forward = forward

    async def env(self, field: str) -> Any:
        environment = await self._client.get_environment()
        return environment[field]

    async def env_update(self, field: str, value: Any) -> None:
        environment = await self._client.get_environment()
        environment[field] = value
        await self._client.put_environment(environment)

    async def forward(self, tool_name: str, args: dict[str, Any]) -> str:
        """Forward a tool call to the real tool."""
        if self._forward is None:
            raise RuntimeError(f"Cannot forward {tool_name}: no upstream is configured.")
        return await self._forward(tool_name, args)
