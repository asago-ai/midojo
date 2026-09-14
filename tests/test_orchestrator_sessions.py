import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from midojo.agent_client import AgentClient, PIAgentClient, SimpleHTTPAgentClient
from midojo.backends.openshell import OpenShellBackend, OpenShellEnvironment
from midojo.mcp_sdk import ControlPlaneClient
from midojo.orchestrator import run_benchmark, run_task


@pytest.fixture
def local_http(app, monkeypatch):
    client_class = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.setdefault("transport", httpx.ASGITransport(app))
        return client_class(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return factory


class ReportingAgent(AgentClient):
    def __init__(self, fail=False):
        self.tokens = []
        self.fail = fail

    async def send_task(self, prompt, *, session_token):
        self.tokens.append(session_token)
        sdk = ControlPlaneClient("http://control", token=session_token)
        try:
            await sdk.record_function_call(function="read", args={}, result=prompt)
            if self.fail:
                raise RuntimeError("Agent failed")
            return "New York is 72°F and sunny"
        finally:
            await sdk.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_runner_revokes_sessions_on_success_and_agent_failure(local_http, client, fail):
    run = client.post("/runs", json={"suite_id": "weather"}).json()
    agent = ReportingAgent(fail)
    task = run_task("http://control", agent, run["id"], "weather_new_york", None, {})
    if fail:
        with pytest.raises(RuntimeError, match="Agent failed"):
            await task
    else:
        result = await task
        assert result["utility"] is True
        assert "session_token" not in result
    response = client.get("/agent/environment", headers={"Authorization": f"Bearer {agent.tokens[0]}"})
    assert response.status_code == 401
    evaluations = client.get(f"/runs/{run['id']}").json()["evaluations"]
    assert len(evaluations) == 1
    calls = client.get(f"/runs/{run['id']}/evaluations/{evaluations[0]['id']}/function-calls").json()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_partial_sandbox_setup_is_cleaned_and_session_revoked(local_http, client, suite):
    class Backend:
        environment_type = suite.environment_type
        cleaned = False
        token = ""

        def provision(self, injections):
            return suite.provision_environment(injections)

        def setup(self, env, *, session_token):
            self.token = session_token
            raise RuntimeError("Seed failed")

        def teardown(self):
            self.cleaned = True

    backend = Backend()
    run = client.post("/runs", json={"suite_id": "weather"}).json()
    with pytest.raises(RuntimeError, match="Seed failed"):
        await run_task("http://control", ReportingAgent(), run["id"], "weather_new_york", None, {}, backend=backend)
    assert backend.cleaned
    assert client.get("/agent/environment", headers={"Authorization": f"Bearer {backend.token}"}).status_code == 401


@pytest.mark.asyncio
async def test_benchmark_selects_suite_and_creates_unique_sessions(local_http, client, suite, tmp_path):
    agent = ReportingAgent()
    await run_benchmark(
        control_url="http://control",
        agent_client=agent,
        agent_uri="http://agent",
        protocol="http",
        suite=suite,
        suite_name="weather",
        user_task_ids=["weather_new_york", "weather_san_francisco"],
        injection_task_ids=[],
        logdir=tmp_path,
    )
    assert len(set(agent.tokens)) == 2
    output = (tmp_path / "results.json").read_text()
    assert all(token not in output for token in agent.tokens)


@pytest.mark.asyncio
async def test_http_agent_receives_session_header(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"response": "done"})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_class(
            **kwargs,
            transport=httpx.MockTransport(handle),
        ),
    )
    assert await SimpleHTTPAgentClient("http://agent").send_task("task", session_token="token") == "done"
    assert requests[0].headers["X-Midojo-Session"] == "token"
    assert "token" not in requests[0].content.decode()


@pytest.mark.asyncio
async def test_pi_subprocess_receives_session_at_launch(monkeypatch, tmp_path):
    launches = []

    class Process:
        returncode = 0

        async def communicate(self):
            return b"done", b""

    async def launch(*args, **kwargs):
        launches.append(kwargs)
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    agent = PIAgentClient(str(tmp_path), "http://control")
    for token in ["first", "second"]:
        assert await agent.send_task("task", session_token=token) == "done"
    assert [launch["env"]["MIDOJO_SESSION_TOKEN"] for launch in launches] == ["first", "second"]
    assert all(launch["env"]["MIDOJO_URL"] == "http://control" for launch in launches)


def test_openshell_tokens_are_per_sandbox_creation():
    backend = OpenShellBackend("test", image="base", workdir_files={}, env_vars={"MIDOJO_SESSION_TOKEN": "stale"})
    backend.configure(cluster="test", control_url="http://localhost:8090")
    backend._workspace_name = "run"
    backend._pb2 = SimpleNamespace(SandboxSpec=SimpleNamespace, SandboxTemplate=SimpleNamespace)
    backend._client = MagicMock()
    backend._client.create.side_effect = [SimpleNamespace(name="a", id="a"), SimpleNamespace(name="b", id="b")]
    for token in ["first", "second"]:
        backend.setup(OpenShellEnvironment(), session_token=token)
        backend.teardown()
    specs = [call.kwargs["spec"] for call in backend._client.create.call_args_list]
    assert [spec.environment["MIDOJO_SESSION_TOKEN"] for spec in specs] == ["first", "second"]
    assert all(spec.environment["MIDOJO_URL"] == "http://host.openshell.internal:8090" for spec in specs)


@pytest.mark.parametrize("fail", [False, True])
def test_workspace_creation_handles_full_run_ids_and_failure_cleanup(monkeypatch, fail):
    sandbox_client = MagicMock()
    sandbox_client.list_ids.return_value = []
    workspace_client = MagicMock()
    names = []

    def create(name):
        assert len(name) <= 19
        assert name[0].isalpha()
        assert all(char.islower() or char.isdigit() or char == "-" for char in name)
        names.append(name)
        if fail:
            raise RuntimeError("Workspace rejected")

    workspace_client.create.side_effect = create
    monkeypatch.setitem(
        sys.modules,
        "openshell",
        SimpleNamespace(
            SandboxClient=SimpleNamespace(from_active_cluster=lambda **kw: sandbox_client),
            WorkspaceClient=SimpleNamespace(from_sandbox_client=lambda client: workspace_client),
        ),
    )
    monkeypatch.setitem(sys.modules, "openshell._proto", SimpleNamespace(openshell_pb2=object()))
    backend = OpenShellBackend("test", image="base", workdir_files={})
    for run_id in ["a" * 31 + "1", "a" * 31 + "2"]:
        try:
            if fail:
                with pytest.raises(RuntimeError, match="Workspace rejected"):
                    backend.start_run(run_id)
            else:
                backend.start_run(run_id)
        finally:
            backend.end_run()
    assert len(set(names)) == 2
    assert sandbox_client.close.call_count == 2
    if fail:
        sandbox_client.list_ids.assert_not_called()
        workspace_client.delete.assert_not_called()
    else:
        assert [call.args[0] for call in workspace_client.delete.call_args_list] == names
