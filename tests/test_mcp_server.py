import asyncio
from unittest.mock import MagicMock

from agentdojo.functions_runtime import FunctionsRuntime

import midojo.suites.weather.injection_tasks
import midojo.suites.weather.user_tasks  # noqa: F401
from midojo.app.models import BenchmarkSession, SessionHolder
from midojo.app.routers.mcp import create_mcp_server
from midojo.forwarding import MCPForwardingClient
from midojo.suites.weather import task_suite


def _setup_session(session_holder: SessionHolder) -> None:
    environment = task_suite.load_and_inject_default_environment({})
    pre_environment = environment.model_copy(deep=True)
    runtime = FunctionsRuntime(task_suite.tools)
    session_holder.session = BenchmarkSession(
        user_task_id="user_task_0",
        injection_task_id=None,
        pre_environment=pre_environment,
        environment=environment,
        runtime=runtime,
    )


def _mock_forward():
    mock = MagicMock(spec=MCPForwardingClient)
    mock.call_tool.return_value = ""
    MCPForwardingClient._instance = mock
    return mock


def test_tool_registration():
    session_holder = SessionHolder()
    mcp = create_mcp_server(task_suite.tools, session_holder)
    tools = asyncio.run(mcp.list_tools())
    tool_names = {t.name for t in tools}
    assert "get_weather" in tool_names
    assert "list_cities" in tool_names
    assert "send_weather_alert" in tool_names
    assert len(tools) == 3


def test_tool_schemas_exclude_depends_params():
    session_holder = SessionHolder()
    mcp = create_mcp_server(task_suite.tools, session_holder)
    tools = asyncio.run(mcp.list_tools())
    tools_by_name = {t.name: t for t in tools}

    alert = tools_by_name["send_weather_alert"]
    props = set(alert.parameters.get("properties", {}).keys())
    assert props == {"city", "message"}
    assert "alerts" not in props


def test_tool_call_mutates_environment():
    session_holder = SessionHolder()
    mcp = create_mcp_server(task_suite.tools, session_holder)
    _setup_session(session_holder)

    result = asyncio.run(
        mcp.call_tool(
            "send_weather_alert",
            {"city": "Chicago", "message": "Flood warning"},
        )
    )
    assert result is not None

    alerts = session_holder.session.environment.weather_alerts
    assert len(alerts) == 1
    assert alerts[0].city == "Chicago"
    assert alerts[0].message == "Flood warning"


def test_tool_call_records_trace():
    _mock_forward()
    session_holder = SessionHolder()
    mcp = create_mcp_server(task_suite.tools, session_holder)
    _setup_session(session_holder)

    asyncio.run(mcp.call_tool("get_weather", {"city": "New York"}))
    asyncio.run(mcp.call_tool("get_weather", {"city": "Chicago"}))

    trace = session_holder.session.trace
    assert len(trace) == 2
    assert trace[0].function == "get_weather"
    assert trace[1].function == "get_weather"
    assert trace[0].args == {"city": "New York"}
    assert trace[1].args == {"city": "Chicago"}
    assert trace[0].error is None
    assert trace[1].error is None


def test_tool_call_without_session():
    session_holder = SessionHolder()
    mcp = create_mcp_server(task_suite.tools, session_holder)

    try:
        asyncio.run(mcp.call_tool("get_weather", {"city": "New York"}))
        assert False, "Should have raised"
    except Exception as e:
        assert "No task configured" in str(e)
