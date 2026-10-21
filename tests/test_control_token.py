"""The control token guards every route except the agent callbacks and the health check."""

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from midojo.control_plane.config import AppConfig
from midojo.control_plane.main import create_app

TOKEN = "control-secret"
CONTROL = {"Authorization": f"Bearer {TOKEN}"}
# FastAPI's own documentation routes, which aren't API routes.
DOCS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
ROUTES = [
    ("get", "/suites", 200),
    ("get", "/suites/weather", 200),
    ("get", "/suites/weather/tasks/user", 200),
    ("post", "/runs", 201),
]


@pytest.fixture
def guarded(suite) -> TestClient:
    return TestClient(create_app({"weather": suite}, config=AppConfig(control_token=TOKEN)))


@pytest.fixture
def evaluation(guarded) -> tuple[str, dict]:
    run = guarded.post("/runs", headers=CONTROL, json={"suite_name": "weather"}).json()
    response = guarded.post(
        f"/runs/{run['id']}/evaluations", headers=CONTROL, json={"user_task_id": "weather_new_york"}
    )
    assert response.status_code == 201, response.text
    return run["id"], response.json()


def _request(client: TestClient, method: str, path: str, headers: dict | None = None):
    json = {"suite_name": "weather"} if method == "post" else None
    return client.request(method, path, headers=headers, json=json)


@pytest.mark.parametrize("method,path,status", ROUTES)
def test_control_routes_require_the_control_token(guarded, evaluation, method, path, status):
    _, ev = evaluation
    missing = _request(guarded, method, path)
    assert missing.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    for token in ["wrong", ev["session_token"]]:
        rejected = _request(guarded, method, path, {"Authorization": f"Bearer {token}"})
        assert rejected.status_code == 401
        assert rejected.headers["WWW-Authenticate"] == "Bearer"
    assert _request(guarded, method, path, CONTROL).status_code == status


def _takes_control_token(route: APIRoute) -> bool:
    # The agent callbacks take the evaluation's session token instead, and the health check takes none.
    return not route.path.startswith("/agent/") and route.path != "/health"


def test_every_other_route_requires_the_control_token(guarded):
    """Walks the app's routes, so a router included without the control dependency fails here."""
    routes = guarded.app.routes
    assert {route.path for route in routes if not isinstance(route, APIRoute)} <= DOCS
    checked = [
        (method, re.sub(r"\{[^}]+\}", "x", route.path))
        for route in routes
        if isinstance(route, APIRoute) and _takes_control_token(route)
        for method in sorted(route.methods)
    ]
    assert checked
    for method, path in checked:
        response = guarded.request(method, path)
        assert response.status_code == 401, f"{method} {path} answered {response.status_code} without the control token"
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_evaluation_routes_reject_the_session_token(guarded, evaluation):
    run_id, ev = evaluation
    session = {"Authorization": f"Bearer {ev['session_token']}"}
    url = f"/runs/{run_id}/evaluations/{ev['id']}"
    requests = [
        ("get", f"/runs/{run_id}", None),
        ("post", f"/runs/{run_id}/evaluations", {"user_task_id": "weather_new_york"}),
        ("put", f"{url}/environment", {}),
        ("post", f"{url}/observations", {"source": "openshell", "data": {}}),
        ("post", f"{url}/complete", {"agent_output": "done"}),
        ("post", f"{url}/grade", None),
        ("delete", f"{url}/session", None),
    ]
    for method, path, json in requests:
        assert guarded.request(method, path, headers=session, json=json).status_code == 401, path
    assert guarded.get(url, headers=CONTROL).json()["agent_output"] is None
    assert guarded.get("/agent/environment", headers=session).status_code == 200


def test_agent_routes_take_the_session_token_alone(guarded, evaluation):
    _, ev = evaluation
    session = {"Authorization": f"Bearer {ev['session_token']}"}
    assert guarded.get("/agent/environment", headers=session).status_code == 200
    call = {"function": "read", "args": {}, "result": "ok"}
    assert guarded.post("/agent/function-calls", headers=session, json=call).status_code == 201
    assert guarded.get("/agent/environment", headers=CONTROL).status_code == 401


def test_health_needs_no_token(guarded):
    assert guarded.get("/health").status_code == 200
