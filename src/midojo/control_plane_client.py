"""HTTP client for the MiDojo control plane."""

from __future__ import annotations

from typing import Any

import httpx

from midojo.app.models import CreateEvaluationResponse, CreateRunResponse, EvaluationResponse, GradeResponse


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

    async def create_run(self, suite_name: str) -> CreateRunResponse:
        response = await self._http.post(f"{self._base_url}/runs", json={"suite_name": suite_name})
        response.raise_for_status()
        return CreateRunResponse.model_validate(response.json())

    async def create_evaluation(
        self,
        run_id: str,
        user_task_id: str,
        injection_task_id: str | None,
        injections: dict[str, str],
    ) -> CreateEvaluationResponse:
        response = await self._http.post(
            f"{self._base_url}/runs/{run_id}/evaluations",
            json={
                "user_task_id": user_task_id,
                "injection_task_id": injection_task_id,
                "injections": injections,
            },
        )
        response.raise_for_status()
        return CreateEvaluationResponse.model_validate(response.json())

    async def complete_evaluation(self, run_id: str, eval_id: str, agent_output: str) -> None:
        response = await self._http.post(
            f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}/complete", json={"agent_output": agent_output}
        )
        response.raise_for_status()

    async def grade_evaluation(self, run_id: str, eval_id: str) -> GradeResponse:
        response = await self._http.post(f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}/grade")
        response.raise_for_status()
        return GradeResponse.model_validate(response.json())

    async def evaluation(self, run_id: str, eval_id: str) -> EvaluationResponse:
        response = await self._http.get(f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}")
        response.raise_for_status()
        return EvaluationResponse.model_validate(response.json())

    async def record_observations(self, run_id: str, eval_id: str, source: str, data: Any) -> None:
        response = await self._http.post(
            f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}/observations",
            json={"source": source, "data": data},
        )
        response.raise_for_status()

    async def revoke_session(self, run_id: str, eval_id: str) -> None:
        response = await self._http.delete(f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}/session")
        response.raise_for_status()

    def agent(self, session_token: str) -> AgentControlPlaneClient:
        """Access interception endpoints for one evaluation session."""
        return AgentControlPlaneClient(self._base_url, self._http, session_token)


class AgentControlPlaneClient:
    """Access interception endpoints for one evaluation session."""

    def __init__(self, base_url: str, http: httpx.AsyncClient, session_token: str) -> None:
        self._base_url = base_url
        self._http = http
        self._headers = {"Authorization": f"Bearer {session_token}"}

    async def get_environment(self) -> dict[str, Any]:
        response = await self._http.get(f"{self._base_url}/agent/environment", headers=self._headers)
        response.raise_for_status()
        return response.json()

    async def put_environment(self, environment: dict[str, Any]) -> None:
        response = await self._http.put(f"{self._base_url}/agent/environment", json=environment, headers=self._headers)
        response.raise_for_status()

    async def record_function_call(self, *, function: str, args: dict, result: str, error: str | None = None) -> None:
        response = await self._http.post(
            f"{self._base_url}/agent/function-calls",
            headers=self._headers,
            json={"function": function, "args": args, "result": result, "error": error},
        )
        response.raise_for_status()
