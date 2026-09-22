from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner

from midojo import orchestrator


@pytest.fixture
def benchmark(monkeypatch):
    for name in ("MODEL_NAME", "MCP_SERVER_URL", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    benchmark = AsyncMock()
    monkeypatch.setattr(orchestrator, "run_benchmark", benchmark)
    return benchmark


@pytest.mark.parametrize(
    "protocol,missing",
    [
        ("ogx", "MODEL_NAME"),
        ("openai", "MODEL_NAME"),
        ("ogx", "MCP_SERVER_URL"),
        ("openai", "MCP_SERVER_URL"),
        ("openai", "OPENAI_API_KEY"),
    ],
)
def test_missing_inference_config_stops_before_benchmark(benchmark, protocol, missing):
    env = {"MODEL_NAME": "model-id", "MCP_SERVER_URL": "http://tools/mcp", "OPENAI_API_KEY": "test-key"}
    env.pop(missing)
    result = CliRunner().invoke(
        orchestrator.main,
        ["--suite", "weather", "--agent-uri", "http://agent", "--protocol", protocol],
        env=env,
    )
    assert result.exit_code == 2
    assert missing in result.output
    benchmark.assert_not_called()


@pytest.mark.parametrize("protocol", ["ogx", "openai", "http"])
def test_cli_resolves_inference_config_only_for_responses_protocols(benchmark, protocol):
    args = ["--suite", "weather", "--agent-uri", "http://agent", "--protocol", protocol]
    env = {}
    if protocol != "http":
        env = {"MODEL_NAME": "env-model", "MCP_SERVER_URL": "http://env-tools/mcp"}
    if protocol == "openai":
        env["OPENAI_API_KEY"] = "test-key"
        args += ["--model-name", "cli-model", "--mcp-server-url", "http://cli-tools/mcp"]
    result = CliRunner().invoke(orchestrator.main, args, env=env)
    assert result.exit_code == 0, result.exception
    benchmark.assert_awaited_once()
    agent = benchmark.call_args.kwargs["agent_client"]
    if protocol == "ogx":
        assert agent.model == "env-model"
        assert agent.mcp_server_url == "http://env-tools/mcp"
    elif protocol == "openai":
        assert agent.model == "cli-model"
        assert agent.mcp_server_url == "http://cli-tools/mcp"
        assert agent.api_key == "test-key"
