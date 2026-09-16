"""Exercise callback isolation across suites, app instances, and overlapping tasks."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from midojo.app.config import AppConfig
from midojo.app.dependencies import get_config
from midojo.app.main import create_app
from midojo.yaml_task_suite import YAMLTaskSuite


def make_suite(tmp_path, name, field, value):
    path = tmp_path / f"{name}.yaml"
    path.write_text(f"""
environment:
  state:
    {field}: {value}
user_tasks:
  - id: shared_task
    prompt: Work on {name}
    utility:
      env_field_equals:
        field: {field}
        value: {value}
""")
    return YAMLTaskSuite(name, path)


def new_evaluation(client, suite_name="weather", task_id="weather_new_york"):
    response = client.post("/runs", json={"suite_name": suite_name})
    assert response.status_code == 201, response.text
    run = response.json()
    response = client.post(f"/runs/{run['id']}/evaluations", json={"user_task_id": task_id})
    assert response.status_code == 201, response.text
    return run, response.json()


def auth(evaluation):
    return {"Authorization": f"Bearer {evaluation['session_token']}"}


def test_interleaved_suites_validate_and_grade_their_own_environment(tmp_path):
    first = make_suite(tmp_path, "first", "count", 3)
    second = make_suite(tmp_path, "second", "label", "ready")
    client = TestClient(create_app({"first": first, "second": second}))
    run_a, a = new_evaluation(client, "first", "shared_task")
    run_b, b = new_evaluation(client, "second", "shared_task")
    assert client.get("/suites").json() == ["first", "second"]
    assert client.get("/agent/environment", headers=auth(a)).json() == {"count": 3}
    assert client.get("/agent/environment", headers=auth(b)).json() == {"label": "ready"}
    assert client.put("/agent/environment", headers=auth(a), json={"label": "wrong"}).status_code == 422
    assert client.put("/agent/environment", headers=auth(b), json={"label": "changed"}).status_code == 200
    for run, ev, expected in [(run_a, a, True), (run_b, b, False)]:
        url = f"/runs/{run['id']}/evaluations/{ev['id']}"
        client.post(f"{url}/complete", json={"agent_output": "done"})
        assert client.post(f"{url}/grade").json()["utility"] is expected
        assert client.get(f"/runs/{run['id']}").json()["suite_name"] == run["suite_name"]
        assert client.get("/agent/environment", headers=auth(ev)).status_code == 401


def test_parallel_callbacks_stay_with_their_session(client):
    run_a, a = new_evaluation(client)
    run_b, b = new_evaluation(client)

    def report(i):
        ev = a if i % 2 else b
        response = client.post(
            "/agent/function-calls",
            headers=auth(ev),
            json={
                "function": "report",
                "args": {},
                "result": ev["id"],
            },
        )
        assert response.status_code == 201

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(report, range(32)))
    for run, ev in [(run_a, a), (run_b, b)]:
        calls = client.get(f"/runs/{run['id']}/evaluations/{ev['id']}/function-calls").json()
        assert len(calls) == 16
        assert {call["result"] for call in calls} == {ev["id"]}


def test_sessions_are_private_expire_and_cannot_fall_back(client, monkeypatch):
    run, ev = new_evaluation(client)
    url = f"/runs/{run['id']}/evaluations/{ev['id']}"
    assert "session_token" not in client.get(url).json()
    assert ev["session_token"] not in client.get(f"/runs/{run['id']}").text
    assert client.get("/agent/environment").status_code == 401
    assert client.get("/agent/environment", headers={"Authorization": "Bearer unknown"}).status_code == 401
    monkeypatch.setattr("midojo.app.store.time.time", lambda: 10**12)
    assert client.get("/agent/environment", headers=auth(ev)).status_code == 401
    assert (
        client.post(
            "/agent/function-calls",
            headers=auth(ev),
            json={
                "function": "late",
                "args": {},
                "result": "late",
            },
        ).status_code
        == 401
    )
    assert client.get(f"{url}/function-calls").json() == []


def test_session_expiry_uses_per_app_config_and_dependency_overrides(suite, monkeypatch):
    now = [1_700_000_000]
    monkeypatch.setattr("midojo.app.store.time.time", lambda: now[0])
    short_app = create_app({"weather": suite}, config=AppConfig(session_ttl_seconds=5))
    long_app = create_app({"weather": suite}, config=AppConfig(session_ttl_seconds=30))
    short_client, long_client = TestClient(short_app), TestClient(long_app)
    _, short = new_evaluation(short_client)
    _, long = new_evaluation(long_client)
    assert datetime.fromisoformat(short["session_expires_at"]).timestamp() == now[0] + 5
    assert datetime.fromisoformat(long["session_expires_at"]).timestamp() == now[0] + 30

    now[0] += 5
    assert short_client.get("/agent/environment", headers=auth(short)).status_code == 401
    assert long_client.get("/agent/environment", headers=auth(long)).status_code == 200

    short_app.dependency_overrides[get_config] = lambda: AppConfig(session_ttl_seconds=10)
    _, overridden = new_evaluation(short_client)
    assert datetime.fromisoformat(overridden["session_expires_at"]).timestamp() == now[0] + 10


def test_explicit_close_does_not_affect_another_session(client):
    run, ev = new_evaluation(client)
    _, other = new_evaluation(client)
    url = f"/runs/{run['id']}/evaluations/{ev['id']}/session"
    assert client.delete(url).status_code == 204
    assert client.delete(url).status_code == 204
    assert client.get("/agent/environment", headers=auth(ev)).status_code == 401
    assert client.get("/agent/environment", headers=auth(other)).status_code == 200


def test_apps_have_independent_suites_stores_and_routes(suite):
    suites = {"first": suite}
    first = TestClient(create_app(suites))
    second = TestClient(create_app({"second": suite}))
    suites.clear()
    run, ev = new_evaluation(first, "first")
    assert first.get("/suites").json() == ["first"]
    assert second.get("/suites").json() == ["second"]
    assert first.get("/suites/first").json()["name"] == "first"
    assert second.get("/suites/second").json()["name"] == "second"
    assert second.get(f"/runs/{run['id']}").status_code == 404
    assert second.get("/agent/environment", headers=auth(ev)).status_code == 401
    assert first.get("/agent/environment", headers=auth(ev)).status_code == 200
    for client in [first, second]:
        assert client.get("/current/environment").status_code == 404
        assert client.get("/suite").status_code == 404
        assert client.post("/runs", json={"suite_name": "os.path"}).status_code == 404
        paths = client.get("/openapi.json").json()["paths"]
        assert "/suites/{suite_name}" in paths
        assert "/suites/{suite_name}/tasks/user/{task_id}" in paths
        assert "/runs/{run_id}/evaluations/{eval_id}/environment" in paths


def test_run_requires_suite_and_rejects_version_mismatch(client, suite):
    assert client.post("/runs").status_code == 422
    assert client.post("/runs", json={"suite_name": "weather", "suite_version": "wrong"}).status_code == 409
    response = client.post("/runs", json={"suite_name": "weather", "suite_version": suite.version})
    assert response.status_code == 201
    assert response.json()["suite_version"] == suite.version


@pytest.mark.parametrize("name", ["bad name", "bad?name", "bad#name"])
def test_suite_name_constraint_applies_to_app_requests_and_paths(client, suite, name):
    # Registered aliases must be checked even when the suite object's own name is valid.
    with pytest.raises(ValidationError):
        create_app({name: suite})
    response = client.post("/runs", json={"suite_name": name})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "suite_name"]
    for suffix in ("", "/tasks/user", "/tasks/user/task", "/tasks/injection", "/tasks/injection/task"):
        response = client.get(f"/suites/{quote(name, safe='')}{suffix}")
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["path", "suite_name"]


def test_suite_version_tracks_expanded_backend_configuration(tmp_path, monkeypatch):
    path = tmp_path / "suite.yaml"
    path.write_text("""
environment:
  backend:
    type: openshell
    image: '${env.MIDOJO_TEST_IMAGE}'
  state: {}
""")
    monkeypatch.setenv("MIDOJO_TEST_IMAGE", "image-a")
    first = YAMLTaskSuite("versioned", path)
    assert YAMLTaskSuite("versioned", path).version == first.version
    monkeypatch.setenv("MIDOJO_TEST_IMAGE", "image-b")
    assert YAMLTaskSuite("versioned", path).version != first.version
    assert YAMLTaskSuite("versioned", path, version="explicit-v1").version == "explicit-v1"


def test_suite_version_tracks_resolved_payloads(tmp_path):
    path = tmp_path / "suite.yaml"
    path.write_text("""
environment:
  state: {text: '{inject:main}'}
injection_tasks:
  - id: inject
    description: test
    probes:
      main: {source: 'file:payloads.json'}
    security: {output_contains: injected}
""")
    payloads = tmp_path / "payloads.json"
    payloads.write_text('{"id": "test", "description": "test", "payloads": ["first"]}')
    first = YAMLTaskSuite("versioned", path)
    payloads.write_text('{"id": "test", "description": "test", "payloads": ["second"]}')
    assert YAMLTaskSuite("versioned", path).version != first.version
