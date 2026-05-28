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
    names = {t["name"] for t in data}
    assert "get_weather" in names
    assert "send_weather_alert" in names
    alert = next(t for t in data if t["name"] == "send_weather_alert")
    assert "city" in alert["parameters"]["properties"]
    assert "city" in alert["parameters"]["required"]
