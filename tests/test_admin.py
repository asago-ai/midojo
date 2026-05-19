def test_suite_info(client):
    resp = client.get("/suite")
    assert resp.status_code == 200
    data = resp.json()
    assert "user_task_0" in data["user_tasks"]
    assert "injection_task_0" in data["injection_tasks"]
    assert "get_weather" in data["tools"]


def test_list_user_tasks(client):
    resp = client.get("/tasks/user")
    assert resp.status_code == 200
    data = resp.json()
    assert "user_task_0" in data


def test_list_injection_tasks(client):
    resp = client.get("/tasks/injection")
    assert resp.status_code == 200
    data = resp.json()
    assert "injection_task_0" in data


def test_task_detail_user(client):
    resp = client.get("/tasks/user/user_task_0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "user_task_0"
    assert data["type"] == "user"
    assert data["prompt"] is not None
    assert len(data["ground_truth"]) > 0
    assert data["ground_truth"][0]["function"] == "get_weather"


def test_task_detail_injection(client):
    resp = client.get("/tasks/injection/injection_task_0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "injection_task_0"
    assert data["type"] == "injection"
    assert data["description"] is not None


def test_task_detail_unknown_user(client):
    resp = client.get("/tasks/user/nonexistent")
    assert resp.status_code == 404


def test_task_detail_unknown_injection(client):
    resp = client.get("/tasks/injection/nonexistent")
    assert resp.status_code == 404


def test_tools(client):
    resp = client.get("/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    names = {t["name"] for t in data}
    assert "get_weather" in names
    assert "send_weather_alert" in names
    alert = next(t for t in data if t["name"] == "send_weather_alert")
    assert "city" in alert["parameters"]["properties"]
    assert "city" in alert["parameters"]["required"]
