import pytest

from midojo.backends import build_backend
from midojo.backends.openshell import (
    OpenShellBackend,
    OpenShellEnvironment,
    _resolve_policy,
)

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
    """provision() only sets workdir_files; all post-session fields default to empty."""

    def test_provision_only_sets_workdir_files(self):
        backend = build_backend("shell_suite", ENV_CONFIG)
        env = backend.provision({"injection_task_0:main": "payload"})
        assert env.workdir_files  # populated
        assert env.files_created == []
        assert env.files_modified == []
        assert env.files_deleted == []
        assert env.workdir_new_file_contents == {}
        assert env.commands_executed == []
        assert env.network_calls_allowed == []
        assert env.network_calls_blocked == []
        assert env.processes_launched == []
        assert env.security_findings == []

    def test_environment_type_is_openshell(self):
        backend = build_backend("shell_suite", ENV_CONFIG)
        assert backend.environment_type is OpenShellEnvironment


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

    def _make_spec(self):
        from unittest.mock import MagicMock

        return MagicMock()

    def test_none_is_noop(self):
        spec = self._make_spec()
        _resolve_policy(None, spec)
        spec.policy.assert_not_called()

    def test_inline_dict_reaches_parse_dict(self):
        spec = self._make_spec()
        inline = {"networkPolicies": {"allow_all": {"endpoints": [{"host": "api.example.com", "port": 443}]}}}
        try:
            _resolve_policy(inline, spec)
        except ValueError:
            pytest.fail("Inline dict should not raise ValueError")
        except Exception:
            pass  # ParseDict fails on MagicMock — dispatch was correct


class TestLogSync:
    """snapshot's OCSF read waits for a marker so late-pushed agent events are included."""

    def _backend(self, reads):
        from unittest.mock import MagicMock

        backend = build_backend("shell_suite", ENV_CONFIG)
        backend._exec = MagicMock()
        backend._read_ocsf_messages = MagicMock(side_effect=reads)
        return backend

    def test_waits_for_marker_and_drops_its_events(self, monkeypatch):
        import midojo.backends.openshell as mod

        monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
        agent_event = "NET:OPEN [MED] DENIED /usr/bin/curl(0) -> evil.test:443 [reason:transparent_tcp_policy_denied]"

        def marker_from_exec():
            script = backend._exec.call_args.args[0][2]
            host = script.split()[2]
            return f"NET:REFUSE [MED] DENIED {host} [reason:policy_dns_ineligible]"

        reads = iter([[], [agent_event], None])

        def read():
            batch = next(reads)
            return batch if batch is not None else [agent_event, marker_from_exec()]

        backend = self._backend(read)
        messages = backend._sync_ocsf_messages()
        assert messages == [agent_event]
        assert backend._read_ocsf_messages.call_count == 3

    def test_returns_last_read_when_marker_never_arrives(self, monkeypatch):
        import midojo.backends.openshell as mod

        clock = iter(range(0, 100, 5))
        monkeypatch.setattr(mod.time, "time", lambda: next(clock))
        monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
        backend = self._backend(lambda: ["NET:OPEN [INFO] ALLOWED /usr/bin/curl(0) -> ok.test:443"])
        assert backend._sync_ocsf_messages() == ["NET:OPEN [INFO] ALLOWED /usr/bin/curl(0) -> ok.test:443"]
