"""Tests for intercepting a LangChain agent's tool calls with MidojoMiddleware."""

import asyncio
from typing import Any

import httpx
import pytest
import pytest_asyncio
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, ToolException, tool
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from midojo_sdk.langchain import BLOCKED_REASON, MidojoMiddleware, ToolContext
from midojo_sdk.session import MissingSessionError, session_context
from pydantic import Field


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


@pytest_asyncio.fixture
async def session(client, monkeypatch):
    run, evaluation = new_evaluation(client)
    monkeypatch.setenv("MIDOJO_SESSION_TOKEN", evaluation["session_token"])
    return run, evaluation


@pytest.fixture
def midojo(control_http):
    return MidojoMiddleware(control_plane_url="http://control", http=control_http)


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


class ScriptedModel(GenericFakeChatModel):
    """A chat model that calls one tool, then answers."""

    bound_tools: list[Any] = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.bound_tools = list(tools)
        return self


async def call_tool(midojo: MidojoMiddleware, tools: list[BaseTool], name: str, args: dict[str, Any]):
    """Run an agent whose model calls the tool ``name`` once, and return the agent's tool message and model."""
    model = ScriptedModel(
        messages=iter([AIMessage("", tool_calls=[{"name": name, "args": args, "id": "call-1"}]), AIMessage("done")])
    )
    agent = create_agent(model, tools=tools, middleware=[midojo])
    result = await agent.ainvoke({"messages": [HumanMessage("go")]})
    [message] = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    return message, model


@pytest.mark.asyncio
async def test_hook_rewrites_the_real_result(client, session, midojo):
    run, evaluation = session

    @midojo.hook("get_weather")
    async def add_cities(ctx: ToolContext, args: dict, real_result: str) -> str:
        return f"{real_result} ({args['city']} is one of {len(await ctx.env('cities'))} cities)"

    message, model = await call_tool(midojo, [get_weather], "get_weather", {"city": "Boston"})

    assert model.bound_tools == [get_weather]
    cities = client.get(f"/runs/{run['id']}/evaluations/{evaluation['id']}/environment").json()["cities"]
    assert message.content == f"Boston: sunny (Boston is one of {len(cities)} cities)"
    assert message.tool_call_id == "call-1"
    [call] = function_calls(client, run, evaluation)
    assert call["function"] == "get_weather"
    assert call["args"] == {"city": "Boston"}
    assert call["result"] == message.content
    assert call["error"] is None


@pytest.mark.asyncio
async def test_hook_errors_are_recorded_and_returned_to_the_agent(client, session, midojo):
    run, evaluation = session

    @midojo.hook("get_weather")
    async def fail(ctx: ToolContext, args: dict, real_result: str) -> str:
        raise ValueError("hook failed")

    message, _ = await call_tool(midojo, [get_weather], "get_weather", {"city": "Boston"})

    assert message.status == "error"
    assert message.content == "hook failed"
    [call] = function_calls(client, run, evaluation)
    assert call["error"] == "hook failed"


@pytest.mark.asyncio
async def test_blocked_tool_never_runs_and_is_recorded_as_blocked(client, session, midojo):
    run, evaluation = session
    emails_sent.clear()
    midojo.block("send_email")

    message, model = await call_tool(midojo, [send_email], "send_email", {"to": "eve@example.com", "body": "hi"})

    assert model.bound_tools == [send_email]
    assert message.status == "error"
    assert message.content == BLOCKED_REASON
    assert emails_sent == []
    [call] = function_calls(client, run, evaluation)
    assert call["function"] == "send_email"
    assert call["args"] == {"to": "eve@example.com", "body": "hi"}
    assert call["result"] == BLOCKED_REASON
    assert call["blocked"] is True


@pytest.mark.asyncio
async def test_reported_tool_runs_unchanged_and_is_recorded(client, session, midojo):
    run, evaluation = session
    midojo.report("get_weather")

    message, _ = await call_tool(midojo, [get_weather], "get_weather", {"city": "Boston"})

    assert message.content == "Boston: sunny"
    assert message.status == "success"
    [call] = function_calls(client, run, evaluation)
    assert call["function"] == "get_weather"
    assert call["args"] == {"city": "Boston"}
    assert call["result"] == "Boston: sunny"
    assert call["error"] is None
    assert call["blocked"] is False


@pytest.mark.asyncio
async def test_reported_tool_keeps_its_own_error_handling(client, session, midojo):
    run, evaluation = session

    @tool
    def get_forecast(city: str) -> str:
        """Get the forecast for a city."""
        raise ToolException(f"No forecast for {city}.")

    get_forecast.handle_tool_error = True
    midojo.report("get_forecast")

    message, _ = await call_tool(midojo, [get_forecast], "get_forecast", {"city": "Boston"})

    assert message.status == "error"
    assert message.content == "No forecast for Boston."
    [call] = function_calls(client, run, evaluation)
    assert call["error"] == "No forecast for Boston."


@pytest.mark.asyncio
async def test_other_tools_run_unrecorded(client, session, midojo):
    run, evaluation = session
    midojo.block("send_email")

    message, _ = await call_tool(midojo, [get_weather, send_email], "get_weather", {"city": "Boston"})

    assert message.content == "Boston: sunny"
    assert function_calls(client, run, evaluation) == []


@pytest.mark.asyncio
async def test_intercepted_tool_without_session_raises(midojo, monkeypatch):
    monkeypatch.delenv("MIDOJO_SESSION_TOKEN", raising=False)
    emails_sent.clear()
    midojo.report("send_email")

    with pytest.raises(MissingSessionError):
        await call_tool(midojo, [send_email], "send_email", {"to": "eve@example.com", "body": "hi"})
    assert emails_sent == []


@pytest.mark.asyncio
async def test_concurrent_sessions_record_to_their_own_evaluation(client, midojo, monkeypatch):
    monkeypatch.delenv("MIDOJO_SESSION_TOKEN", raising=False)
    evaluations = [new_evaluation(client) for _ in range(2)]
    midojo.report("get_weather")

    async def call(evaluation):
        with session_context(evaluation["session_token"]):
            await asyncio.sleep(0)
            return await call_tool(midojo, [get_weather], "get_weather", {"city": evaluation["id"]})

    await asyncio.gather(*[call(evaluation) for _, evaluation in evaluations])

    for run, evaluation in evaluations:
        assert [c["args"] for c in function_calls(client, run, evaluation)] == [{"city": evaluation["id"]}]


@pytest.mark.asyncio
async def test_tool_node_takes_the_interceptor(client, session, midojo):
    run, evaluation = session
    emails_sent.clear()
    midojo.block("send_email")
    tool_node = ToolNode([send_email], awrap_tool_call=midojo.awrap_tool_call)
    graph = StateGraph(MessagesState).add_node("tools", tool_node).set_entry_point("tools").compile()

    tool_call = {"name": "send_email", "args": {"to": "eve@example.com", "body": "hi"}, "id": "call-1"}
    result = await graph.ainvoke({"messages": [AIMessage("", tool_calls=[tool_call])]})

    message = result["messages"][-1]
    assert message.content == BLOCKED_REASON
    assert emails_sent == []
    assert [c["blocked"] for c in function_calls(client, run, evaluation)] == [True]


def test_a_tool_is_intercepted_once(midojo):
    midojo.block("send_email")

    with pytest.raises(ValueError, match="send_email is already intercepted"):
        midojo.report("send_email")
