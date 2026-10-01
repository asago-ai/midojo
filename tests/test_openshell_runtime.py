from types import SimpleNamespace

from openshell._proto import openshell_pb2

from midojo.runtimes import build_runtime
from midojo.runtimes.openshell import OpenShellRuntime, _resolve_policy
from midojo.runtimes.openshell.logs import parse_ocsf_lines
from midojo.suite_definition import OpenShellRuntimeDefinition

POLICY = {"networkPolicies": {"api": {"endpoints": [{"host": "api.example.com", "port": 443}]}}}


def test_build_runtime_passes_the_definition_through():
    definition = OpenShellRuntimeDefinition(image="pi", agent_command=["pi", "-p", "--no-session"], policy=POLICY)
    runtime = build_runtime("shell_suite", definition)
    assert isinstance(runtime, OpenShellRuntime)
    assert runtime.image == "pi"
    assert runtime.agent_command == ["pi", "-p", "--no-session"]
    assert runtime.policy == POLICY


def test_ocsf_pairs_each_exit_with_the_latest_launch_of_its_pid():
    lines = [
        "PROC:LAUNCH [INFO] curl(41) [cmd:curl https://example.com]",
        "PROC:TERMINATE [INFO] curl(41) [exit:6]",
        "PROC:LAUNCH [INFO] cat(41) [cmd:cat notes.txt]",
        "PROC:TERMINATE [INFO] cat(41) [exit:0]",
        "PROC:LAUNCH [INFO] sh(42) [cmd:sh]",
    ]
    assert [p.exit_code for p in parse_ocsf_lines(lines).processes] == [6, 0, None]


def test_configure_sets_gateway_and_control_url():
    runtime = OpenShellRuntime("shell_suite", image="pi")
    runtime.configure(cluster="my-gateway", control_url="http://localhost:8080")
    assert (runtime._cluster, runtime._control_url) == ("my-gateway", "http://localhost:8080")


class TestPolicy:
    """_resolve_policy accepts None (no-op) or an inline dict."""

    def test_none_is_noop(self):
        spec = openshell_pb2.SandboxSpec()
        _resolve_policy(None, spec)
        assert not spec.HasField("policy")

    def test_inline_dict_fills_policy(self):
        spec = openshell_pb2.SandboxSpec()
        inline = {"networkPolicies": {"allow_all": {"endpoints": [{"host": "api.example.com", "port": 443}]}}}
        _resolve_policy(inline, spec)
        assert spec.policy.network_policies["allow_all"].endpoints[0].host == "api.example.com"


class _FakeSandboxClient:
    """Records the SDK calls the runtime makes against one sandbox."""

    def __init__(self):
        self.exec_calls = []
        self.logs_requests = []
        self._stub = self

    def exec(self, sandbox_name, command, **kwargs):
        self.exec_calls.append((sandbox_name, command, kwargs))

    def GetSandboxLogs(self, request, timeout):  # noqa: N802 - mirrors the gRPC stub
        self.logs_requests.append(request)
        return openshell_pb2.GetSandboxLogsResponse()


def _runtime_with_sandbox() -> tuple[OpenShellRuntime, _FakeSandboxClient]:
    runtime = OpenShellRuntime("shell_suite", image="pi")
    client = _FakeSandboxClient()
    runtime._client = client
    runtime._workspace_name = "midojo-shell-abc123"
    runtime._ref = SimpleNamespace(name="midojo-eval-1")
    runtime._start_ms = 1_790_000_000_123
    return runtime, client


def test_exec_addresses_the_sandbox_by_name_within_the_workspace():
    runtime, client = _runtime_with_sandbox()
    runtime.exec_agent("hello", timeout_seconds=30)
    name, _, kwargs = client.exec_calls[0]
    assert name == "midojo-eval-1"
    assert kwargs["workspace"] == "midojo-shell-abc123"


def test_log_fetch_scopes_to_the_sandbox_since_the_evaluation_started():
    runtime, client = _runtime_with_sandbox()
    runtime._fetch_ocsf()
    request = client.logs_requests[0]
    assert request.sandbox == "midojo-eval-1"
    assert request.workspace_scope.workspace == "midojo-shell-abc123"
    assert request.since_time.ToMilliseconds() == 1_790_000_000_123
    assert list(request.sources) == ["sandbox"]
