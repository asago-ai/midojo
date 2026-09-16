import sys
from unittest.mock import call, patch

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from midojo.serve import main
from midojo.suites import get_suite


@pytest.fixture
def external_suite(tmp_path, monkeypatch):
    package = tmp_path / "serve_test_suites"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "custom.py").write_text(
        "from pathlib import Path\n"
        "from midojo.yaml_task_suite import YAMLTaskSuite\n"
        'task_suite = YAMLTaskSuite("custom", Path(__file__).with_name("suite.yaml"))\n'
    )
    yaml_path = package / "suite.yaml"
    yaml_path.write_text("environment:\n  state: {message: ready}\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        yield "serve_test_suites.custom", yaml_path
    finally:
        sys.modules.pop("serve_test_suites.custom", None)
        sys.modules.pop("serve_test_suites", None)


def test_serve_requires_explicit_suites():
    with patch("midojo.serve.uvicorn.run") as serve:
        result = CliRunner().invoke(main, [])
    assert result.exit_code == 2
    assert "Missing option '--load-suite'" in result.output
    serve.assert_not_called()


def test_serve_eagerly_loads_only_selected_suites(external_suite):
    external_name, _ = external_suite
    with (
        patch("midojo.serve.get_suite", wraps=get_suite) as load,
        patch("midojo.serve.uvicorn.run") as serve,
    ):

        def check_startup(app, **kwargs):
            assert load.call_args_list == [call("weather"), call(external_name)]

        serve.side_effect = check_startup
        result = CliRunner().invoke(
            main,
            ["--load-suite", "weather", "--load-suite", external_name, "--load-suite", "weather"],
        )
        assert result.exit_code == 0, result.exception
        serve.assert_called_once()
        client = TestClient(serve.call_args.args[0])
        assert client.get("/suites").json() == sorted(["weather", external_name])
        for name in ["weather", external_name]:
            for _ in range(2):
                response = client.post("/runs", json={"suite_name": name})
                assert response.status_code == 201
                assert response.json()["suite_name"] == name
        assert client.get("/suites/minibank").status_code == 404
        assert client.post("/runs", json={"suite_name": "minibank"}).status_code == 404
        assert client.post("/runs", json={"suite_name": "os.path"}).status_code == 404
        assert load.call_count == 2


def test_serve_rejects_missing_suite_before_starting():
    with patch("midojo.serve.uvicorn.run") as serve:
        result = CliRunner().invoke(main, ["--load-suite", "missing_test_suite"])
    assert result.exit_code != 0
    assert isinstance(result.exception, ModuleNotFoundError)
    serve.assert_not_called()


def test_serve_rejects_invalid_suite_before_starting(external_suite):
    name, yaml_path = external_suite
    yaml_path.write_text("environment:\n  state: []\n")
    with patch("midojo.serve.uvicorn.run") as serve:
        result = CliRunner().invoke(main, ["--load-suite", "weather", "--load-suite", name])
    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
    assert "environment.state" in str(result.exception)
    serve.assert_not_called()
