from fastapi import FastAPI
from fastapi.testclient import TestClient

import midojo.suites.weather as suite_module
import midojo.suites.weather.injection_tasks
import midojo.suites.weather.user_tasks  # noqa: F401
from midojo.app.routers.admin import create_admin_router
from midojo.suites.weather import task_suite


def _make_client() -> TestClient:
    router = create_admin_router(task_suite, suite_module)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_check():
    client = _make_client()
    resp = client.get("/admin/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["passed"] is True
    assert "user_task_0" in data["user_tasks"]
    assert data["user_tasks"]["user_task_0"]["passed"] is True


def test_suite_info():
    client = _make_client()
    resp = client.get("/admin/suite")
    assert resp.status_code == 200
    data = resp.json()
    assert "user_task_0" in data["user_tasks"]
    assert "injection_task_0" in data["injection_tasks"]
    assert "get_weather" in data["tools"]
    assert len(data["injection_vectors"]) > 0
    first_vector = next(iter(data["injection_vectors"].values()))
    assert "description" in first_vector
    assert "default" in first_vector


def test_environment():
    client = _make_client()
    resp = client.get("/admin/environment")
    assert resp.status_code == 200
    data = resp.json()
    assert "cities" in data


def test_injection_candidates():
    client = _make_client()
    resp = client.get("/admin/injection-candidates")
    assert resp.status_code == 200
    data = resp.json()
    assert "user_task_0" in data
    assert isinstance(data["user_task_0"], list)


def test_task_detail_user():
    client = _make_client()
    resp = client.get("/admin/tasks/user_task_0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "user_task_0"
    assert data["type"] == "user"
    assert data["prompt"] is not None
    assert len(data["ground_truth"]) > 0
    assert data["ground_truth"][0]["function"] == "get_weather"


def test_task_detail_injection():
    client = _make_client()
    resp = client.get("/admin/tasks/injection_task_0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "injection_task_0"
    assert data["type"] == "injection"
    assert data["goal"] is not None


def test_task_detail_unknown():
    client = _make_client()
    resp = client.get("/admin/tasks/nonexistent")
    assert resp.status_code == 404


def test_tools():
    client = _make_client()
    resp = client.get("/admin/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    names = {t["name"] for t in data}
    assert "get_weather" in names
    assert "send_weather_alert" in names
    alert = next(t for t in data if t["name"] == "send_weather_alert")
    assert "city" in alert["parameters"]["properties"]
    assert "city" in alert["parameters"]["required"]
