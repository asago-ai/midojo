import asyncio
import json
import re
import sys
from enum import Enum
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from midojo.agent_client import AgentClient, PIAgentClient, SimpleHTTPAgentClient
from midojo.backends.openshell import OpenShellBackend, OpenShellEnvironment
from midojo.mcp_sdk import ControlPlaneClient
from midojo.orchestrator import run_benchmark, run_task


@pytest.fixture
def gateway(monkeypatch):
    """Fake the optional OpenShell/gRPC dependencies at their SDK boundary."""

    class StatusCode(Enum):
        ALREADY_EXISTS = 1
        UNAVAILABLE = 2

    class RpcError(Exception):
        def __init__(self, status):
            self.status = status

        def code(self):
            return self.status

    sandboxes = MagicMock()
    sandboxes.list_ids.return_value = []
    sandboxes.create.side_effect = lambda **kw: SimpleNamespace(name=kw["name"], id=kw["name"])
    workspaces = MagicMock()
    workspaces.create.side_effect = lambda name, **kw: SimpleNamespace(name=name)
    monkeypatch.setitem(sys.modules, "grpc", SimpleNamespace(RpcError=RpcError, StatusCode=StatusCode))
    monkeypatch.setitem(
        sys.modules,
        "openshell",
        SimpleNamespace(
            SandboxClient=SimpleNamespace(from_active_cluster=lambda **kw: sandboxes),
            WorkspaceClient=SimpleNamespace(from_sandbox_client=lambda client: workspaces),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "openshell._proto",
        SimpleNamespace(
            openshell_pb2=SimpleNamespace(SandboxSpec=SimpleNamespace, SandboxTemplate=SimpleNamespace),
        ),
    )
    return SimpleNamespace(sandboxes=sandboxes, workspaces=workspaces, RpcError=RpcError, StatusCode=StatusCode)


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
    run = client.post("/runs", json={"suite_name": "weather"}).json()
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

        def setup(self, env, *, session_token, eval_id, user_task_id, injection_task_id):
            evaluation = client.get(f"/runs/{run['id']}/evaluations/{eval_id}").json()
            assert evaluation["user_task_id"] == user_task_id
            assert evaluation["injection_task_id"] == injection_task_id
            self.token = session_token
            raise RuntimeError("Seed failed")

        def teardown(self):
            self.cleaned = True

    backend = Backend()
    run = client.post("/runs", json={"suite_name": "weather"}).json()
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
    assert json.loads(output)["suite_name"] == "weather"
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


def test_openshell_tokens_and_labels_are_per_sandbox_creation(gateway):
    backend = OpenShellBackend("test", image="base", workdir_files={}, env_vars={"MIDOJO_SESSION_TOKEN": "stale"})
    backend.configure(cluster="test", control_url="http://localhost:8090")
    run_id = "a" * 32
    suite_name = "external.Document_Assistant-v1"
    backend.start_run(run_id, suite_name=suite_name)
    assert len(backend.workspace_name) <= 19
    assert re.fullmatch(r"midojo-[a-z0-9]+-[a-z0-9]+", backend.workspace_name)
    for idx, injection in enumerate(["exfiltrate_report_via_curl", None]):
        backend.setup(
            OpenShellEnvironment(),
            session_token=f"secret-{idx}",
            eval_id=f"{idx:010x}",
            user_task_id="summarize_q4_report",
            injection_task_id=injection,
        )
        backend.teardown()
    calls = gateway.sandboxes.create.call_args_list
    specs = [call.kwargs["spec"] for call in calls]
    assert [spec.environment["MIDOJO_SESSION_TOKEN"] for spec in specs] == ["secret-0", "secret-1"]
    assert all(spec.environment["MIDOJO_URL"] == "http://host.openshell.internal:8090" for spec in specs)
    for idx, call in enumerate(calls):
        labels = call.kwargs["labels"]
        assert labels["midojo.suite"] == suite_name
        assert labels["midojo.run-id"] == run_id
        assert labels["midojo.eval-id"] == f"{idx:010x}"
        assert labels["midojo.user-task"] == "summarize_q4_report"
        assert f"secret-{idx}" not in str(labels)
        assert call.kwargs["name"] == f"eval-{idx:010x}"
        assert call.kwargs["workspace"] == backend.workspace_name
    assert calls[0].kwargs["labels"]["midojo.injection-task"] == "exfiltrate_report_via_curl"
    assert "midojo.injection-task" not in calls[1].kwargs["labels"]
    backend.end_run()


@pytest.mark.parametrize(
    "status,succeed,expected_attempts",
    [
        ("ALREADY_EXISTS", True, 2),
        ("ALREADY_EXISTS", False, 5),
        ("UNAVAILABLE", False, 1),
    ],
)
def test_workspaces_retry_only_conflicts_without_reusing_or_deleting_them(
    gateway,
    status,
    succeed,
    expected_attempts,
):
    backend = OpenShellBackend("document_assistant", image="base", workdir_files={})
    attempts = []

    def create(*args, **kwargs):
        name = args[0] if args else kwargs["name"]
        attempts.append(name)
        if not succeed or len(attempts) == 1:
            raise gateway.RpcError(gateway.StatusCode[status])
        return SimpleNamespace(name=name, id=name)

    gateway.workspaces.create.side_effect = create
    try:
        if succeed:
            backend.start_run("run")
            actual = backend.workspace_name
            assert actual == attempts[-1]
            assert actual != attempts[0]
        else:
            with pytest.raises(gateway.RpcError) as error:
                backend.start_run("run")
            assert error.value.code() == gateway.StatusCode[status]
            assert backend.workspace_name == ""
    finally:
        backend.teardown()
        backend.end_run()
    assert len(attempts) == expected_attempts
    assert len(set(attempts)) == len(attempts)
    assert [call.args[0] for call in gateway.workspaces.delete.call_args_list] == ([attempts[-1]] if succeed else [])


def test_sandbox_creation_failure_does_not_rename_reuse_or_delete_existing_sandbox(gateway):
    status = "ALREADY_EXISTS"
    backend = OpenShellBackend("document_assistant", image="base", workdir_files={})
    backend.start_run("run")
    gateway.sandboxes.create.side_effect = gateway.RpcError(gateway.StatusCode[status])
    try:
        with pytest.raises(gateway.RpcError) as error:
            backend.setup(
                OpenShellEnvironment(),
                session_token="secret",
                eval_id="c896124bda",
                user_task_id="summarize_q4_report",
                injection_task_id=None,
            )
        assert error.value.code() == gateway.StatusCode[status]
        assert backend._ref is None
    finally:
        backend.teardown()
        backend.end_run()
    assert gateway.sandboxes.create.call_count == 1
    assert gateway.sandboxes.create.call_args.kwargs["name"] == "eval-c896124bda"
    gateway.sandboxes.wait_ready.assert_not_called()
    gateway.sandboxes.delete.assert_not_called()
