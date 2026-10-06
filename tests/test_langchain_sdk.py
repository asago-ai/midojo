"""Tests for intercepting LangChain tools with MidojoToolkit."""

import asyncio

import httpx
import pytest
import pytest_asyncio
from langchain_core.tools import tool
from midojo_sdk.langchain import MidojoToolkit, ToolContext
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
