from fastapi import FastAPI
from fastapi.testclient import TestClient

import midojo.suites.weather.injection_tasks
import midojo.suites.weather.user_tasks  # noqa: F401
from midojo.app import state
from midojo.app.models import TraceEntry
from midojo.app.routers import runs
from midojo.suites.weather import task_suite


def _make_client() -> TestClient:
    state.suite = task_suite
    state.runs = {}
    state.current_eval = None
    app = FastAPI()
    app.include_router(runs.router)
    return TestClient(app)


def _create_run(client: TestClient) -> str:
    resp = client.post("/runs")
    assert resp.status_code == 201
    return resp.json()["id"]


def _create_evaluation(client: TestClient, run_id: str, **kwargs) -> dict:
    payload = {"user_task_id": "user_task_0", **kwargs}
    resp = client.post(f"/runs/{run_id}/evaluations", json=payload)
    assert resp.status_code == 201
    return resp.json()


def test_create_run():
    client = _make_client()
    run_id = _create_run(client)
    assert len(run_id) > 0


def test_get_run():
    client = _make_client()
    run_id = _create_run(client)
    resp = client.get(f"/runs/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == run_id
    assert data["evaluations"] == []


def test_get_run_not_found():
    client = _make_client()
    resp = client.get("/runs/nonexistent")
    assert resp.status_code == 404


def test_create_evaluation():
    client = _make_client()
    run_id = _create_run(client)
    data = _create_evaluation(client, run_id)
    assert "id" in data
    assert "prompt" in data
    assert "weather" in data["prompt"].lower()


def test_create_evaluation_with_injection():
    client = _make_client()
    run_id = _create_run(client)
    data = _create_evaluation(
        client,
        run_id,
        injection_task_id="injection_task_0",
        injections={"injection_weather_notes": "IGNORE PREVIOUS INSTRUCTIONS"},
    )
    assert "id" in data
    assert "prompt" in data


def test_create_evaluation_unknown_task():
    client = _make_client()
    run_id = _create_run(client)
    resp = client.post(f"/runs/{run_id}/evaluations", json={"user_task_id": "nonexistent"})
    assert resp.status_code == 400


def test_get_evaluation():
    client = _make_client()
    run_id = _create_run(client)
    eval_data = _create_evaluation(client, run_id)
    eval_id = eval_data["id"]

    resp = client.get(f"/runs/{run_id}/evaluations/{eval_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == eval_id
    assert data["user_task_id"] == "user_task_0"
    assert data["completed"] is False


def test_complete_and_grade_utility_only():
    client = _make_client()
    run_id = _create_run(client)
    eval_data = _create_evaluation(client, run_id)
    eval_id = eval_data["id"]

    resp = client.post(
        f"/runs/{run_id}/evaluations/{eval_id}/complete",
        json={"model_output": "The weather in New York is 72°F and sunny."},
    )
    assert resp.status_code == 200

    resp = client.get(f"/runs/{run_id}/evaluations/{eval_id}")
    assert resp.json()["completed"] is True

    resp = client.post(f"/runs/{run_id}/evaluations/{eval_id}/grade")
    assert resp.status_code == 200
    data = resp.json()
    assert data["utility"] is True
    assert data["security"] is False


def test_grade_before_complete():
    client = _make_client()
    run_id = _create_run(client)
    eval_data = _create_evaluation(client, run_id)
    eval_id = eval_data["id"]

    resp = client.post(f"/runs/{run_id}/evaluations/{eval_id}/grade")
    assert resp.status_code == 400


def test_trace_recording():
    client = _make_client()
    run_id = _create_run(client)
    eval_data = _create_evaluation(client, run_id)
    eval_id = eval_data["id"]

    evaluation = state.current_eval
    evaluation.runtime.run_function(evaluation.environment, "get_weather", {"city": "New York"})
    evaluation.trace.append(
        TraceEntry(
            function="get_weather",
            args={"city": "New York"},
            result="...",
            error=None,
            timestamp="2024-01-01T00:00:00Z",
        )
    )

    resp = client.get(f"/runs/{run_id}/evaluations/{eval_id}")
    assert resp.status_code == 200
    trace = resp.json()["trace"]
    assert len(trace) == 1
    assert trace[0]["function"] == "get_weather"


def test_full_task_lifecycle():
    """End-to-end: setup with injection, simulate tool calls, complete, grade."""
    client = _make_client()
    run_id = _create_run(client)
    eval_data = _create_evaluation(
        client,
        run_id,
        injection_task_id="injection_task_0",
        injections={},
    )
    eval_id = eval_data["id"]

    evaluation = state.current_eval
    result, _ = evaluation.runtime.run_function(evaluation.environment, "get_weather", {"city": "New York"})
    evaluation.trace.append(
        TraceEntry(
            function="get_weather",
            args={"city": "New York"},
            result=str(result),
            error=None,
            timestamp="2024-01-01T00:00:00Z",
        )
    )

    client.post(
        f"/runs/{run_id}/evaluations/{eval_id}/complete",
        json={"model_output": "The weather in New York is 72°F and sunny."},
    )

    resp = client.post(f"/runs/{run_id}/evaluations/{eval_id}/grade")
    data = resp.json()
    assert data["utility"] is True
    assert data["security"] is False


def test_run_aggregates_evaluations():
    client = _make_client()
    run_id = _create_run(client)

    eval_data = _create_evaluation(client, run_id)
    eval_id = eval_data["id"]
    client.post(
        f"/runs/{run_id}/evaluations/{eval_id}/complete",
        json={"model_output": "The weather in New York is 72°F and sunny."},
    )
    client.post(f"/runs/{run_id}/evaluations/{eval_id}/grade")

    resp = client.get(f"/runs/{run_id}")
    data = resp.json()
    assert len(data["evaluations"]) == 1
    assert data["evaluations"][0]["id"] == eval_id
    assert data["evaluations"][0]["completed"] is True
    assert data["evaluations"][0]["utility"] is True
