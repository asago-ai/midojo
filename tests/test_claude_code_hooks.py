"""Tests for the Claude Code hook handler.

Verifies that the hook handler correctly:
1. Reads injection plan from the control plane
2. Matches tool-type instructions by tool name
3. Applies injection to tool output
4. Records function calls
5. Returns the correct Claude Code hook response format
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from midojo.hooks.claude_code import handle_post_tool_use


@pytest.fixture()
def http_client(client: TestClient) -> httpx.Client:
    """Wrap Starlette's TestClient as an httpx.Client for the hook handler."""
    return client  # type: ignore[return-value] — TestClient is httpx.Client compatible for our usage


@pytest.fixture()
def _eval_with_plan(client: TestClient) -> tuple[TestClient, str, str]:
    """Create a run + eval with a tool injection plan."""
    run_id = client.post("/runs").json()["id"]
    eval_id = client.post(
        f"/runs/{run_id}/evaluations",
        json={
            "user_task_id": "weather_new_york",
            "injection_plan": [
                {"type": "tool", "payload": "INJECTED PAYLOAD", "target_tool": "get_weather", "mode": "embed"},
            ],
        },
    ).json()["id"]
    return client, run_id, eval_id


class TestPostToolUseHandler:
    def test_injects_matching_tool(self, _eval_with_plan, http_client):
        cp_client, run_id, eval_id = _eval_with_plan

        response = handle_post_tool_use(
            {
                "tool_name": "get_weather",
                "tool_input": {"city": "New York"},
                "tool_output": json.dumps({"city": "NYC", "description": "Sunny and warm today"}),
            },
            control_url="http://testserver",
            http_client=http_client,
        )

        assert response is not None
        assert response["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        updated = response["hookSpecificOutput"]["updatedToolOutput"]
        assert "INJECTED PAYLOAD" in updated
        assert "Sunny and warm" in updated

    def test_no_injection_for_unmatched_tool(self, _eval_with_plan, http_client):
        cp_client, run_id, eval_id = _eval_with_plan

        response = handle_post_tool_use(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
                "tool_output": "file1.txt\nfile2.txt",
            },
            control_url="http://testserver",
            http_client=http_client,
        )

        assert response is None

    def test_no_injection_without_plan(self, client, http_client):
        run_id = client.post("/runs").json()["id"]
        client.post(
            f"/runs/{run_id}/evaluations",
            json={"user_task_id": "weather_new_york"},
        )

        response = handle_post_tool_use(
            {
                "tool_name": "get_weather",
                "tool_input": {},
                "tool_output": "72F sunny",
            },
            control_url="http://testserver",
            http_client=http_client,
        )

        assert response is None

    def test_records_function_call(self, _eval_with_plan, http_client):
        cp_client, run_id, eval_id = _eval_with_plan

        handle_post_tool_use(
            {
                "tool_name": "get_weather",
                "tool_input": {"city": "NYC"},
                "tool_output": json.dumps({"description": "Sunny"}),
            },
            control_url="http://testserver",
            http_client=http_client,
        )

        calls = cp_client.get(f"/runs/{run_id}/evaluations/{eval_id}/function-calls").json()
        assert len(calls) == 1
        assert calls[0]["function"] == "get_weather"
        assert "INJECTED PAYLOAD" in calls[0]["result"]

    def test_records_even_without_injection(self, client, http_client):
        run_id = client.post("/runs").json()["id"]
        eval_id = client.post(
            f"/runs/{run_id}/evaluations",
            json={"user_task_id": "weather_new_york"},
        ).json()["id"]

        handle_post_tool_use(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "echo hi"},
                "tool_output": "hi",
            },
            control_url="http://testserver",
            http_client=http_client,
        )

        calls = client.get(f"/runs/{run_id}/evaluations/{eval_id}/function-calls").json()
        assert len(calls) == 1
        assert calls[0]["function"] == "Bash"
        assert calls[0]["result"] == "hi"

    def test_replace_mode(self, client, http_client):
        run_id = client.post("/runs").json()["id"]
        client.post(
            f"/runs/{run_id}/evaluations",
            json={
                "user_task_id": "weather_new_york",
                "injection_plan": [
                    {"type": "tool", "payload": "FULL REPLACEMENT", "mode": "replace"},
                ],
            },
        )

        response = handle_post_tool_use(
            {
                "tool_name": "any_tool",
                "tool_input": {},
                "tool_output": "original output",
            },
            control_url="http://testserver",
            http_client=http_client,
        )

        assert response is not None
        assert response["hookSpecificOutput"]["updatedToolOutput"] == "FULL REPLACEMENT"

    def test_wildcard_target_tool(self, client, http_client):
        run_id = client.post("/runs").json()["id"]
        client.post(
            f"/runs/{run_id}/evaluations",
            json={
                "user_task_id": "weather_new_york",
                "injection_plan": [
                    {"type": "tool", "payload": "WILDCARD", "target_tool": None, "mode": "append"},
                ],
            },
        )

        response = handle_post_tool_use(
            {
                "tool_name": "any_tool_name",
                "tool_input": {},
                "tool_output": "original",
            },
            control_url="http://testserver",
            http_client=http_client,
        )

        assert response is not None
        assert "WILDCARD" in response["hookSpecificOutput"]["updatedToolOutput"]
        assert "original" in response["hookSpecificOutput"]["updatedToolOutput"]
