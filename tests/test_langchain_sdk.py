"""Tests for intercepting LangChain tools with MidojoToolkit."""

import asyncio

import httpx
import pytest
import pytest_asyncio
from langchain_core.tools import ToolException, tool
from midojo_sdk.langchain import BLOCKED_REASON, MidojoToolkit, ToolContext
from midojo_sdk.session import MissingSessionError, session_context


def new_evaluation(client):
    run = client.post("/runs", json={"suite_name": "weather"}).json()
    evaluation = client.post(f"/runs/{run['id']}/evaluations", json={"user_task_id": "weather_new_york"}).json()
    return run, evaluation


def function_calls(client, run, evaluation):
    return client.get(f"/runs/{run['id']}/evaluations/{evaluation['id']}/function-calls").json()


@pytest_asyncio.fixture
async def control_http(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app)) as http:
        yield http


@tool
def get_weather(city: str) -> str:
    """Get the weather for a city."""
    return f"{city}: sunny"


emails_sent = []


@tool
def send_email(to: str, body: str) -> str:
    """Send an email."""
    emails_sent.append(to)
    return "sent"


def assert_looks_like(lc_tool, real_tool):
    assert lc_tool.name == real_tool.name
    assert lc_tool.description == real_tool.description
    assert lc_tool.tool_call_schema.model_json_schema() == real_tool.tool_call_schema.model_json_schema()


def test_tool_registration_hides_ctx():
    toolkit = MidojoToolkit(control_plane_url="http://localhost:9999")

    @toolkit.tool()
    async def my_tool(ctx: ToolContext, name: str) -> str:
        """A test tool."""
        return f"hello {name}"

    [lc_tool] = toolkit.get_tools()
    assert lc_tool.name == "my_tool"
    assert lc_tool.description == "A test tool."
    assert set(lc_tool.args) == {"name"}


def test_tool_requires_ctx():
    toolkit = MidojoToolkit(control_plane_url="http://localhost:9999")

    with pytest.raises(TypeError, match="ToolContext"):

        @toolkit.tool()
        async def bad_tool(name: str) -> str:
            """Missing ctx."""
            return name


@pytest.mark.asyncio
async def test_tool_reads_env_forwards_and_records(client, control_http, monkeypatch):
    run, evaluation = new_evaluation(client)
    monkeypatch.setenv("MIDOJO_SESSION_TOKEN", evaluation["session_token"])
    toolkit = MidojoToolkit(control_plane_url="http://control", real_tools=[get_weather], http=control_http)

    @toolkit.tool()
    async def get_weather_intercepted(ctx: ToolContext, city: str) -> str:
        """Get the weather for a city."""
        assert city in await ctx.env("cities")
        await ctx.env_update("weather_alerts", [{"city": city, "message": "seen"}])
        return await ctx.forward("get_weather", {"city": city})

    [lc_tool] = toolkit.get_tools()
    assert await lc_tool.ainvoke({"city": "New York"}) == "New York: sunny"

    [call] = function_calls(client, run, evaluation)
    assert call["function"] == "get_weather_intercepted"
    assert call["args"] == {"city": "New York"}
    assert call["result"] == "New York: sunny"
    assert call["error"] is None
    environment = client.get(f"/runs/{run['id']}/evaluations/{evaluation['id']}/environment").json()
    assert environment["weather_alerts"] == [{"city": "New York", "message": "seen"}]


@pytest.mark.asyncio
async def test_concurrent_sessions_record_to_their_own_evaluation(client, control_http, monkeypatch):
    monkeypatch.delenv("MIDOJO_SESSION_TOKEN", raising=False)
    evaluations = [new_evaluation(client) for _ in range(2)]
    toolkit = MidojoToolkit(control_plane_url="http://control", http=control_http)

    @toolkit.tool()
    async def echo(ctx: ToolContext, message: str) -> str:
        """Echo a message."""
        await asyncio.sleep(0)
        return message

    [lc_tool] = toolkit.get_tools()

    async def call(evaluation):
        with session_context(evaluation["session_token"]):
            return await lc_tool.ainvoke({"message": evaluation["id"]})

    await asyncio.gather(*[call(evaluation) for _, evaluation in evaluations])

    for run, evaluation in evaluations:
        assert [c["result"] for c in function_calls(client, run, evaluation)] == [evaluation["id"]]


@pytest.mark.asyncio
async def test_tool_errors_are_recorded_and_returned_to_the_agent(client, control_http, monkeypatch):
    run, evaluation = new_evaluation(client)
    monkeypatch.setenv("MIDOJO_SESSION_TOKEN", evaluation["session_token"])
    toolkit = MidojoToolkit(control_plane_url="http://control", http=control_http)

    @toolkit.tool()
    async def forward_without_real_tools(ctx: ToolContext, city: str) -> str:
        """Forward to a real tool that isn't configured."""
        return await ctx.forward("get_weather", {"city": city})

    [lc_tool] = toolkit.get_tools()
    message = await lc_tool.ainvoke(
        {"type": "tool_call", "id": "call-1", "name": "forward_without_real_tools", "args": {"city": "New York"}}
    )

    assert message.status == "error"
    assert message.content == "Cannot forward get_weather: no upstream is configured."
    [call] = function_calls(client, run, evaluation)
    assert call["function"] == "forward_without_real_tools"
    assert call["error"] == "Cannot forward get_weather: no upstream is configured."


@pytest.mark.asyncio
async def test_forward_rejects_unknown_real_tool(client, control_http, monkeypatch):
    _, evaluation = new_evaluation(client)
    monkeypatch.setenv("MIDOJO_SESSION_TOKEN", evaluation["session_token"])
    toolkit = MidojoToolkit(control_plane_url="http://control", real_tools=[get_weather], http=control_http)

    @toolkit.tool()
    async def get_forecast(ctx: ToolContext, city: str) -> str:
        """Get the forecast for a city."""
        return await ctx.forward("get_forecast", {"city": city})

    [lc_tool] = toolkit.get_tools()
    assert await lc_tool.ainvoke({"city": "New York"}) == "Cannot forward get_forecast: no real tool has that name."


@pytest.mark.asyncio
async def test_tool_without_session_raises(monkeypatch):
    monkeypatch.delenv("MIDOJO_SESSION_TOKEN", raising=False)
    toolkit = MidojoToolkit(control_plane_url="http://localhost:9999")

    @toolkit.tool()
    async def my_tool(ctx: ToolContext, name: str) -> str:
        """A test tool."""
        return name

    [lc_tool] = toolkit.get_tools()
    with pytest.raises(MissingSessionError):
        await lc_tool.ainvoke({"name": "x"})


@pytest.mark.asyncio
async def test_tool_call_from_an_agent_returns_a_tool_message(client, control_http, monkeypatch):
    run, evaluation = new_evaluation(client)
    monkeypatch.setenv("MIDOJO_SESSION_TOKEN", evaluation["session_token"])
    toolkit = MidojoToolkit(control_plane_url="http://control", real_tools=[get_weather], http=control_http)

    @toolkit.tool()
    async def get_weather_intercepted(ctx: ToolContext, city: str) -> str:
        """Get the weather for a city."""
        return await ctx.forward("get_weather", {"city": city})

    [lc_tool] = toolkit.get_tools()
    message = await lc_tool.ainvoke(
        {"type": "tool_call", "id": "call-1", "name": "get_weather_intercepted", "args": {"city": "Boston"}}
    )

    assert message.tool_call_id == "call-1"
    assert message.content == "Boston: sunny"
    assert [c["args"] for c in function_calls(client, run, evaluation)] == [{"city": "Boston"}]


@pytest.mark.asyncio
async def test_blocked_tool_never_runs_and_is_recorded_as_blocked(client, control_http, monkeypatch):
    run, evaluation = new_evaluation(client)
    monkeypatch.setenv("MIDOJO_SESSION_TOKEN", evaluation["session_token"])
    emails_sent.clear()
    toolkit = MidojoToolkit(control_plane_url="http://control", http=control_http)
    toolkit.block(send_email)

    [lc_tool] = toolkit.get_tools()
    assert_looks_like(lc_tool, send_email)
    message = await lc_tool.ainvoke(
        {"type": "tool_call", "id": "call-1", "name": "send_email", "args": {"to": "eve@example.com", "body": "hi"}}
    )

    assert message.status == "error"
    assert message.content == BLOCKED_REASON
    assert emails_sent == []
    [call] = function_calls(client, run, evaluation)
    assert call["function"] == "send_email"
    assert call["args"] == {"to": "eve@example.com", "body": "hi"}
    assert call["result"] == BLOCKED_REASON
    assert call["blocked"] is True


def test_tool_names_are_unique():
    toolkit = MidojoToolkit(control_plane_url="http://localhost:9999")
    toolkit.block(send_email)

    with pytest.raises(ValueError, match="already has a tool named send_email"):
        toolkit.block(send_email)


@pytest.mark.asyncio
async def test_reported_tool_runs_unchanged_and_is_recorded(client, control_http, monkeypatch):
    run, evaluation = new_evaluation(client)
    monkeypatch.setenv("MIDOJO_SESSION_TOKEN", evaluation["session_token"])
    toolkit = MidojoToolkit(control_plane_url="http://control", http=control_http)
    toolkit.report(get_weather)

    [lc_tool] = toolkit.get_tools()
    assert_looks_like(lc_tool, get_weather)
    tool_call = {"type": "tool_call", "id": "call-1", "name": "get_weather", "args": {"city": "Boston"}}
    assert await lc_tool.ainvoke(tool_call) == await get_weather.ainvoke(tool_call)

    [call] = function_calls(client, run, evaluation)
    assert call["function"] == "get_weather"
    assert call["args"] == {"city": "Boston"}
    assert call["result"] == "Boston: sunny"
    assert call["error"] is None
    assert call["blocked"] is False


@pytest.mark.asyncio
async def test_reported_tool_keeps_its_own_error_handling(client, control_http, monkeypatch):
    run, evaluation = new_evaluation(client)
    monkeypatch.setenv("MIDOJO_SESSION_TOKEN", evaluation["session_token"])

    @tool
    def get_forecast(city: str) -> str:
        """Get the forecast for a city."""
        raise ToolException(f"No forecast for {city}.")

    get_forecast.handle_tool_error = True
    toolkit = MidojoToolkit(control_plane_url="http://control", http=control_http)
    toolkit.report(get_forecast)

    [lc_tool] = toolkit.get_tools()
    message = await lc_tool.ainvoke(
        {"type": "tool_call", "id": "call-1", "name": "get_forecast", "args": {"city": "Boston"}}
    )

    assert message.status == "error"
    assert message.content == "No forecast for Boston."
    [call] = function_calls(client, run, evaluation)
    assert call["error"] == "No forecast for Boston."


@pytest.mark.asyncio
async def test_hook_rewrites_the_real_result(client, control_http, monkeypatch):
    run, evaluation = new_evaluation(client)
    monkeypatch.setenv("MIDOJO_SESSION_TOKEN", evaluation["session_token"])
    toolkit = MidojoToolkit(control_plane_url="http://control", http=control_http)

    @toolkit.hook(get_weather)
    async def add_cities(ctx: ToolContext, args: dict, real_result: str) -> str:
        return f"{real_result} ({args['city']} is one of {len(await ctx.env('cities'))} cities)"

    [lc_tool] = toolkit.get_tools()
    assert_looks_like(lc_tool, get_weather)
    message = await lc_tool.ainvoke(
        {"type": "tool_call", "id": "call-1", "name": "get_weather", "args": {"city": "Boston"}}
    )

    cities = client.get(f"/runs/{run['id']}/evaluations/{evaluation['id']}/environment").json()["cities"]
    assert message.content == f"Boston: sunny (Boston is one of {len(cities)} cities)"
    [call] = function_calls(client, run, evaluation)
    assert call["function"] == "get_weather"
    assert call["args"] == {"city": "Boston"}
    assert call["result"] == message.content
    assert call["error"] is None


@pytest.mark.asyncio
async def test_hook_errors_are_recorded_and_returned_to_the_agent(client, control_http, monkeypatch):
    run, evaluation = new_evaluation(client)
    monkeypatch.setenv("MIDOJO_SESSION_TOKEN", evaluation["session_token"])
    toolkit = MidojoToolkit(control_plane_url="http://control", http=control_http)

    @toolkit.hook(get_weather)
    async def fail(ctx: ToolContext, args: dict, real_result: str) -> str:
        raise ValueError("hook failed")

    [lc_tool] = toolkit.get_tools()
    message = await lc_tool.ainvoke(
        {"type": "tool_call", "id": "call-1", "name": "get_weather", "args": {"city": "Boston"}}
    )

    assert message.status == "error"
    assert message.content == "hook failed"
    [call] = function_calls(client, run, evaluation)
    assert call["error"] == "hook failed"
