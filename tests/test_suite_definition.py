"""Validate authored suite data before constructing runtime objects."""

from copy import deepcopy
from typing import Any
from unittest.mock import Mock

import pytest
import yaml
from pydantic import ValidationError

from midojo.backends import DictEnvironmentBackend
from midojo.suites import get_suite
from midojo.verifiers import VerificationResult
from midojo.yaml_task_suite import YAMLTaskSuite


@pytest.fixture
def raw() -> dict[str, Any]:
    return {
        "environment": {"state": {"text": "{inject:main}"}},
        "user_tasks": [{"id": "read", "prompt": "Read the text", "utility": {"output_contains": "done"}}],
        "injection_tasks": [
            {
                "id": "inject",
                "description": "Replace the text",
                "probes": {"main": {"payload": "injected"}},
                "security": {"output_contains": "injected"},
            }
        ],
    }


def load(tmp_path, raw, *, name="test", **kwargs):
    path = tmp_path / "suite.yaml"
    path.write_text(yaml.safe_dump(raw))
    return YAMLTaskSuite(name, path, **kwargs)


@pytest.mark.parametrize(
    "name",
    ["../weather", "query?x", "bad name"],
)
def test_invalid_names_are_rejected_by_definition_and_import_loader(tmp_path, raw, monkeypatch, name):
    with pytest.raises(ValueError, match="name"):
        load(tmp_path, raw, name=name)
    import_module = Mock()
    monkeypatch.setattr("midojo.suites.importlib.import_module", import_module)
    with pytest.raises(ValidationError):
        get_suite(name)
    import_module.assert_not_called()


def test_empty_document_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="suite.yaml: expected a YAML mapping"):
        load(tmp_path, None)


@pytest.mark.parametrize(
    "raw,location",
    [
        ({"environment": {"state": []}}, ("environment", "state")),
        ({"environment": {}, "user_task": []}, ("user_task",)),
        (
            {"environment": {}, "user_tasks": [{"id": "x", "prompt": 12, "utility": {}}]},
            ("user_tasks", 0, "prompt"),
        ),
        ({"environment": {}, "injection_tasks": [{"id": "x", "description": "x"}]}, ("injection_tasks", 0, "security")),
    ],
)
def test_structure_errors_include_file_and_field_before_backend_setup(tmp_path, monkeypatch, raw, location):
    build = Mock()
    monkeypatch.setattr("midojo.yaml_task_suite.build_backend", build)
    with pytest.raises(ValueError, match="suite.yaml") as error:
        load(tmp_path, raw)
    cause = error.value.__cause__
    assert isinstance(cause, ValidationError)
    assert location in [detail["loc"] for detail in cause.errors()]
    build.assert_not_called()


@pytest.mark.parametrize("field", ["user_tasks", "injection_tasks"])
def test_duplicate_task_ids_are_rejected_within_each_task_kind(tmp_path, raw, field):
    raw[field].append(deepcopy(raw[field][0]))
    with pytest.raises(ValueError, match="duplicate task ID") as error:
        load(tmp_path, raw)
    assert field in str(error.value)


def test_user_and_injection_tasks_can_share_an_id(tmp_path, raw):
    raw["user_tasks"][0]["id"] = "inject"
    suite = load(tmp_path, raw)
    assert "inject" in suite.user_tasks and "inject" in suite.injection_tasks


def test_empty_payload_is_valid(tmp_path, raw):
    raw["injection_tasks"][0]["probes"]["main"]["payload"] = ""
    suite = load(tmp_path, raw)
    assert suite.injection_tasks["inject"].probes == {"main": ""}


def test_yaml_name_must_agree_with_supplied_name(tmp_path, raw):
    raw["name"] = "test"
    assert load(tmp_path, raw).definition.name == "test"
    with pytest.raises(ValueError, match="does not match the supplied name"):
        load(tmp_path, raw, name="another")


def test_definition_preserves_backend_and_verifier_extension_data(tmp_path, raw, monkeypatch):
    from midojo.backends import _BACKENDS
    from midojo.verifiers import _VERIFIERS

    captured = {}

    def factory(name, environment, config):
        captured.update(name=name, environment=environment, config=config)
        return DictEnvironmentBackend(name, environment["state"])

    class CustomVerifier:
        name = "custom"

        def parse(self, spec):
            assert spec == {"answer": "done", "nested": [1, {"x": True}]}
            return spec["answer"]

        def assess(self, check, context):
            return VerificationResult(passed=context.agent_output == check, reason="custom output check")

        def evaluate(self, check, context):
            return context.agent_output == check

    monkeypatch.setitem(_BACKENDS, "custom", factory)
    monkeypatch.setitem(_VERIFIERS, "custom", CustomVerifier())
    raw["environment"]["backend"] = {"type": "custom", "custom_options": [1, {"x": True}]}
    raw["environment"]["custom_environment_field"] = {"value": 7}
    raw["user_tasks"][0]["utility"] = {"custom": {"answer": "done", "nested": [1, {"x": True}]}}
    raw["injection_tasks"][0]["security"] = deepcopy(raw["user_tasks"][0]["utility"])
    suite = load(tmp_path, raw)
    assert captured == {
        "name": "test",
        "environment": raw["environment"],
        "config": {"custom_options": [1, {"x": True}]},
    }
    env = suite.provision_environment(suite.get_probes_for_task("inject"))
    assert env.model_dump() == {"text": "injected"}
    grade = suite.grade("read", "inject", "done", env, env, [])
    assert grade == {"utility": True, "security": True, "security_reason": "custom output check"}


def test_definition_works_with_explicit_backend(tmp_path, raw):
    backend = DictEnvironmentBackend("custom", {"other": "state"})
    raw["environment"]["backend"] = "provided-by-caller"
    suite = load(tmp_path, raw, backend=backend)
    assert suite.backend is backend
    assert suite.provision_environment({}).model_dump() == {"other": "state"}
