"""HTTP client for the MiDojo control plane."""

from __future__ import annotations

from typing import Any

import httpx


class ControlPlaneClient:
    """Access orchestrator and interception endpoints on one control plane."""

    def __init__(self, base_url: str, *, http: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=300.0)
        self._owns_http = http is None

    async def __aenter__(self) -> ControlPlaneClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def suite_info(self, suite_name: str) -> dict[str, Any]:
        response = await self._http.get(f"{self._base_url}/suites/{suite_name}")
        response.raise_for_status()
        return response.json()

    async def create_run(self, suite_name: str, suite_version: str) -> str:
        response = await self._http.post(
            f"{self._base_url}/runs", json={"suite_name": suite_name, "suite_version": suite_version}
        )
        response.raise_for_status()
        return response.json()["id"]

    async def create_evaluation(
        self,
        run_id: str,
        user_task_id: str,
        injection_task_id: str | None,
        injections: dict[str, str],
    ) -> dict[str, Any]:
        response = await self._http.post(
            f"{self._base_url}/runs/{run_id}/evaluations",
            json={
                "user_task_id": user_task_id,
                "injection_task_id": injection_task_id,
                "injections": injections,
            },
        )
        response.raise_for_status()
        return response.json()

    async def complete_evaluation(self, run_id: str, eval_id: str, agent_output: str) -> None:
        response = await self._http.post(
            f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}/complete", json={"agent_output": agent_output}
        )
        response.raise_for_status()

    async def grade_evaluation(self, run_id: str, eval_id: str) -> dict[str, Any]:
        response = await self._http.post(f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}/grade")
        response.raise_for_status()
        return response.json()

    async def evaluation(self, run_id: str, eval_id: str) -> dict[str, Any]:
        response = await self._http.get(f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}")
        response.raise_for_status()
        return response.json()

    async def function_calls(self, run_id: str, eval_id: str) -> list[dict[str, Any]]:
        response = await self._http.get(f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}/function-calls")
        response.raise_for_status()
        return response.json()

    async def put_evaluation_environment(self, run_id: str, eval_id: str, environment: dict[str, Any]) -> None:
        response = await self._http.put(
            f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}/environment", json=environment
        )
        response.raise_for_status()

    async def revoke_session(self, run_id: str, eval_id: str) -> None:
        response = await self._http.delete(f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}/session")
        response.raise_for_status()

    def _agent_headers(self, session_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {session_token}"}

    async def get_environment(self, session_token: str) -> dict[str, Any]:
        response = await self._http.get(
            f"{self._base_url}/agent/environment", headers=self._agent_headers(session_token)
        )
        response.raise_for_status()
        return response.json()

    async def put_environment(self, session_token: str, environment: dict[str, Any]) -> None:
        response = await self._http.put(
            f"{self._base_url}/agent/environment", json=environment, headers=self._agent_headers(session_token)
        )
        response.raise_for_status()

    async def record_function_call(
        self, session_token: str, *, function: str, args: dict, result: str, error: str | None = None
    ) -> None:
        response = await self._http.post(
            f"{self._base_url}/agent/function-calls",
            headers=self._agent_headers(session_token),
            json={"function": function, "args": args, "result": result, "error": error},
        )
        response.raise_for_status()

    async def record_observations(self, session_token: str, source: str, data: Any) -> None:
        response = await self._http.post(
            f"{self._base_url}/agent/observations",
            headers=self._agent_headers(session_token),
            json={"source": source, "data": data},
        )
        response.raise_for_status()
