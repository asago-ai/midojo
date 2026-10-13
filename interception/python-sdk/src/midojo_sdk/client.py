"""HTTP client for the control plane's /agent API."""

from __future__ import annotations

from typing import Any

import httpx


class AgentControlPlaneClient:
    """Access interception endpoints for one evaluation session."""

    def __init__(self, base_url: str, session_token: str, *, http: httpx.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._headers = {"Authorization": f"Bearer {session_token}"}

    async def get_environment(self) -> dict[str, Any]:
        response = await self._http.get(f"{self._base_url}/agent/environment", headers=self._headers)
        response.raise_for_status()
        return response.json()

    async def put_environment(self, environment: dict[str, Any]) -> None:
        response = await self._http.put(f"{self._base_url}/agent/environment", json=environment, headers=self._headers)
        response.raise_for_status()

    async def record_function_call(
        self, *, function: str, args: dict, result: str, error: str | None = None, blocked: bool = False
    ) -> None:
        response = await self._http.post(
            f"{self._base_url}/agent/function-calls",
            headers=self._headers,
            json={"function": function, "args": args, "result": result, "error": error, "blocked": blocked},
        )
        response.raise_for_status()
