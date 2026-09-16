"""Exercise callback isolation across suites, app instances, and overlapping tasks."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from midojo.app.config import AppConfig
from midojo.app.dependencies import get_config
from midojo.app.main import create_app
from midojo.mcp_sdk import ControlPlaneClient
from midojo.session import MidojoSessionMiddleware, MissingSessionError, session_context
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


def test_apps_have_independent_catalogs_stores_and_routes(suite):
    first = TestClient(create_app({"first": suite}))
    second = TestClient(create_app({"second": suite}))
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
def test_suite_name_constraint_applies_to_catalog_requests_and_paths(client, suite, name):
    # Registered aliases must be checked even when the suite object's own name is valid.
    for suites in ([name], {name: suite}):
        with pytest.raises(ValidationError):
            create_app(suites)
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


@pytest.mark.asyncio
async def test_persistent_agent_propagates_context_without_restart(app, client, monkeypatch):
    monkeypatch.delenv("MIDOJO_SESSION_TOKEN", raising=False)
    run_a, a = new_evaluation(client)
    run_b, b = new_evaluation(client)
    sdk = ControlPlaneClient("http://control", http=httpx.AsyncClient(transport=httpx.ASGITransport(app)))
    agent = FastAPI()
    agent.add_middleware(MidojoSessionMiddleware)

    @agent.post("/")
    async def task(body: dict):
        await asyncio.sleep(0)
        await sdk.record_function_call(function="task", args={}, result=body["prompt"])
        return {"response": "done"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(agent), base_url="http://agent") as http:
        responses = await asyncio.gather(
            *[
                http.post("/", headers={"X-Midojo-Session": ev["session_token"]}, json={"prompt": ev["id"]})
                for ev in [a, b]
            ]
        )
        assert all(response.status_code == 200 for response in responses)
    for run, ev in [(run_a, a), (run_b, b)]:
        calls = client.get(f"/runs/{run['id']}/evaluations/{ev['id']}/function-calls").json()
        assert [call["result"] for call in calls] == [ev["id"]]
    with pytest.raises(MissingSessionError):
        await sdk.get_environment()
    with session_context(a["session_token"]):
        assert "cities" in await sdk.get_environment()
    client.delete(f"/runs/{run_a['id']}/evaluations/{a['id']}/session")
    with session_context(a["session_token"]), pytest.raises(httpx.HTTPStatusError) as failure:
        await sdk.record_function_call(function="late", args={}, result="late")
    assert failure.value.response.status_code == 401
    await sdk.aclose()


@pytest.mark.asyncio
async def test_remote_mcp_server_reads_session_from_each_request(app, client):
    from midojo.mcp_sdk import MidojoMCP, ToolContext

    run_a, a = new_evaluation(client)
    run_b, b = new_evaluation(client)
    mcp = MidojoMCP("report", control_plane_url="http://control")
    await mcp._client.aclose()

    mcp._client = ControlPlaneClient("http://control", http=httpx.AsyncClient(transport=httpx.ASGITransport(app)))

    @mcp.tool()
    async def report(ctx: ToolContext, message: str) -> str:
        assert "New York" in await ctx.env("cities")
        return message

    mcp_app = mcp._fastmcp.http_app(path="/mcp", stateless_http=True)
    async with mcp_app.router.lifespan_context(mcp_app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(mcp_app), base_url="http://mcp") as http:
            for ev in [a, b]:
                response = await http.post(
                    "/mcp",
                    headers={
                        "X-Midojo-Session": ev["session_token"],
                        "Accept": "application/json, text/event-stream",
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "report", "arguments": {"message": ev["id"]}},
                    },
                )
                assert response.status_code == 200, response.text
                assert ev["id"] in response.text
    for run, ev in [(run_a, a), (run_b, b)]:
        calls = client.get(f"/runs/{run['id']}/evaluations/{ev['id']}/function-calls").json()
        assert [call["result"] for call in calls] == [ev["id"]]
    await mcp._client.aclose()


@pytest.mark.asyncio
async def test_a2a_transport_keeps_executor_callbacks_scoped(app, client, monkeypatch):
    from a2a.server.agent_execution import AgentExecutor
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes.agent_card_routes import create_agent_card_routes
    from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.types import AgentCapabilities, AgentCard, AgentInterface, Message, Part, Role
    from starlette.applications import Starlette

    from midojo.agent_client import A2AAgentClient

    run_a, a = new_evaluation(client)
    run_b, b = new_evaluation(client)
    sdk = ControlPlaneClient("http://control", http=httpx.AsyncClient(transport=httpx.ASGITransport(app)))

    class Executor(AgentExecutor):
        async def execute(self, context, event_queue):
            assert context.message is not None
            prompt = context.message.parts[0].text
            await asyncio.sleep(0)
            await sdk.record_function_call(function="a2a_task", args={}, result=prompt)
            await event_queue.enqueue_event(Message(role=Role.ROLE_AGENT, parts=[Part(text=prompt)]))

        async def cancel(self, context, event_queue):
            raise NotImplementedError

    card = AgentCard(
        name="test",
        description="test",
        version="1",
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[AgentInterface(url="http://agent/", protocol_binding="JSONRPC")],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
    )
    handler = DefaultRequestHandler(agent_executor=Executor(), task_store=InMemoryTaskStore(), agent_card=card)
    agent = Starlette(routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")])
    agent.add_middleware(MidojoSessionMiddleware)
    client_class = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client_class(**kw, transport=httpx.ASGITransport(agent)))
    try:
        results = await asyncio.gather(
            *[A2AAgentClient("http://agent/").send_task(ev["id"], session_token=ev["session_token"]) for ev in [a, b]]
        )
        assert results == [a["id"], b["id"]]
        for run, ev in [(run_a, a), (run_b, b)]:
            calls = client.get(f"/runs/{run['id']}/evaluations/{ev['id']}/function-calls").json()
            assert [call["result"] for call in calls] == [ev["id"]]
    finally:
        await sdk.aclose()
