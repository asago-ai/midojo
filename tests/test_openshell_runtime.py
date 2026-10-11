from types import SimpleNamespace
from unittest.mock import MagicMock

from openshell._proto import openshell_pb2

import midojo.runtimes.openshell as openshell_runtime
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
    runtime._read_ocsf_messages()
    request = client.logs_requests[0]
    assert request.sandbox == "midojo-eval-1"
    assert request.workspace_scope.workspace == "midojo-shell-abc123"
    assert request.since_time.ToMilliseconds() == 1_790_000_000_123
    assert list(request.sources) == ["sandbox"]


class TestLogSync:
    """The OCSF read waits for a marker so late-pushed agent events are included."""

    def _runtime(self, reads):
        runtime = OpenShellRuntime("shell_suite", image="pi")
        runtime._exec = MagicMock()
        runtime._read_ocsf_messages = MagicMock(side_effect=reads)
        return runtime

    def test_waits_for_marker_and_drops_its_events(self, monkeypatch):
        monkeypatch.setattr(openshell_runtime.time, "sleep", lambda _s: None)
        agent_event = "NET:OPEN [MED] DENIED /usr/bin/curl(0) -> evil.test:443 [reason:transparent_tcp_policy_denied]"

        def marker_from_exec():
            script = runtime._exec.call_args.args[0][2]
            host = script.split()[2]
            return f"NET:REFUSE [MED] DENIED {host} [reason:policy_dns_ineligible]"

        reads = iter([[], [agent_event], None])

        def read():
            batch = next(reads)
            return batch if batch is not None else [agent_event, marker_from_exec()]

        runtime = self._runtime(read)
        assert runtime._sync_ocsf_messages() == [agent_event]
        assert runtime._read_ocsf_messages.call_count == 3

    def test_returns_last_read_when_marker_never_arrives(self, monkeypatch):
        clock = iter(range(0, 100, 5))
        monkeypatch.setattr(openshell_runtime.time, "time", lambda: next(clock))
        monkeypatch.setattr(openshell_runtime.time, "sleep", lambda _s: None)
        allowed = "NET:OPEN [INFO] ALLOWED /usr/bin/curl(0) -> ok.test:443"
        runtime = self._runtime(lambda: [allowed])
        assert runtime._sync_ocsf_messages() == [allowed]


def test_build_runtime_passes_the_log_globs_through():
    definition = OpenShellRuntimeDefinition(image="pi", logs=["/tmp/*.log", "notes.txt"])
    runtime = build_runtime("shell_suite", definition)
    assert isinstance(runtime, OpenShellRuntime)
    assert runtime._logs == ["/tmp/*.log", "notes.txt"]


class _LoggingSandbox:
    """A sandbox whose exec answers the log collector's commands from a fake filesystem."""

    def __init__(self, files, log_lines=(), fail_logs=False):
        self.files = files
        self.log_lines = log_lines
        self.fail_logs = fail_logs
        self.logs_requests = []
        self._stub = self

    def exec(self, sandbox_name, command, **kwargs):
        if command[:2] == ["sh", "-c"]:
            listed = [p for p in self.files if any(p.startswith(g.rstrip("*")) for g in command[4:])]
            return SimpleNamespace(stdout="\n".join(listed), stderr="", exit_code=0)
        if command[0] == "cat":
            return SimpleNamespace(stdout=self.files[command[1]], stderr="", exit_code=0)
        return SimpleNamespace(stdout="agent answer", stderr="Traceback: boom", exit_code=1)

    def GetSandboxLogs(self, request, timeout):  # noqa: N802 - mirrors the gRPC stub
        if self.fail_logs:
            raise RuntimeError("gateway unavailable")
        self.logs_requests.append(request)
        response = openshell_pb2.GetSandboxLogsResponse()
        for source, level, message in self.log_lines:
            line = response.logs.add(source=source, level=level, target="openshell_supervisor", message=message)
            line.event_time.FromMilliseconds(1_790_000_000_500)
        return response


def _collecting_runtime(sandbox, logs):
    runtime = OpenShellRuntime("shell_suite", image="pi", logs=logs)
    runtime._client = sandbox
    runtime._workspace_name = "midojo-shell-abc123"
    runtime._ref = SimpleNamespace(name="eval-1")
    runtime._created_ms = 1_790_000_000_000
    return runtime


class TestCollectLogs:
    def test_saves_agent_output_openshell_log_and_declared_files(self, tmp_path):
        sandbox = _LoggingSandbox(
            files={"/tmp/server.log": "server started\n", "/sandbox/workdir/notes.txt": "a note\n"},
            log_lines=[("sandbox", "OCSF", "NET:OPEN [MED] DENIED /usr/bin/python3(0) -> example.com:443")],
        )
        runtime = _collecting_runtime(sandbox, logs=["/tmp/*", "/sandbox/workdir/notes.txt"])
        runtime.exec_agent("hello", timeout_seconds=30)

        runtime.collect_logs(tmp_path / "eval-1")

        out = tmp_path / "eval-1"
        assert (out / "agent.stdout").read_text() == "agent answer"
        assert (out / "agent.stderr").read_text() == "Traceback: boom"
        assert (out / "sandbox/tmp/server.log").read_text() == "server started\n"
        assert (out / "sandbox/sandbox/workdir/notes.txt").read_text() == "a note\n"
        assert "[sandbox] [OCSF] [openshell_supervisor] NET:OPEN [MED] DENIED" in (out / "openshell.log").read_text()

    def test_openshell_log_starts_at_sandbox_creation_from_all_sources(self, tmp_path):
        sandbox = _LoggingSandbox(files={})
        _collecting_runtime(sandbox, logs=[]).collect_logs(tmp_path)
        request = sandbox.logs_requests[0]
        assert (request.sandbox, request.workspace_scope.workspace) == ("eval-1", "midojo-shell-abc123")
        assert request.since_time.ToMilliseconds() == 1_790_000_000_000
        assert list(request.sources) == []

    def test_one_failing_part_does_not_stop_the_others(self, tmp_path):
        sandbox = _LoggingSandbox(files={"/tmp/server.log": "still here\n"}, fail_logs=True)
        _collecting_runtime(sandbox, logs=["/tmp/server.log"]).collect_logs(tmp_path)
        assert not (tmp_path / "openshell.log").exists()
        assert (tmp_path / "sandbox/tmp/server.log").read_text() == "still here\n"

    def test_without_a_sandbox_saves_nothing(self, tmp_path):
        OpenShellRuntime("shell_suite", image="pi").collect_logs(tmp_path / "eval-1")
        assert not (tmp_path / "eval-1").exists()
