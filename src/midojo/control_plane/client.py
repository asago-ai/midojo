"""HTTP client for the MiDojo control plane."""

from __future__ import annotations

import httpx
from pydantic import BaseModel

from midojo.control_plane.models import CreateEvaluationResponse, CreateRunResponse, EvaluationResponse, GradeResponse


class ControlPlaneClient:
    """Access orchestrator endpoints on one control plane."""

    def __init__(self, base_url: str, *, token: str | None = None, http: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
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
        response = await self._http.post(
            f"{self._base_url}/runs", headers=self._headers, json={"suite_name": suite_name}
        )
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
            headers=self._headers,
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
            f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}/complete",
            headers=self._headers,
            json={"agent_output": agent_output},
        )
        response.raise_for_status()

    async def grade_evaluation(self, run_id: str, eval_id: str) -> GradeResponse:
        response = await self._http.post(
            f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}/grade", headers=self._headers
        )
        response.raise_for_status()
        return GradeResponse.model_validate(response.json())

    async def evaluation(self, run_id: str, eval_id: str) -> EvaluationResponse:
        response = await self._http.get(f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}", headers=self._headers)
        response.raise_for_status()
        return EvaluationResponse.model_validate(response.json())

    async def record_observations(self, run_id: str, eval_id: str, source: str, observed: BaseModel) -> None:
        response = await self._http.post(
            f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}/observations",
            headers=self._headers,
            json={"source": source, "data": observed.model_dump(mode="json")},
        )
        response.raise_for_status()

    async def revoke_session(self, run_id: str, eval_id: str) -> None:
        response = await self._http.delete(
            f"{self._base_url}/runs/{run_id}/evaluations/{eval_id}/session", headers=self._headers
        )
        response.raise_for_status()
