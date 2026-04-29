"""A2A weather agent for midojo E2E testing.

A minimal A2A-compliant agent that:
1. Publishes an AgentCard at /.well-known/agent-card.json
2. Connects to midojo's MCP server for tool access
3. Uses an OpenAI-compatible LLM (via LiteLLM) for reasoning
4. Speaks the A2A JSON-RPC protocol for task handling
"""

from __future__ import annotations

import json
import os

import uvicorn
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Message,
    Part,
    Role,
)
from dotenv import load_dotenv
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from openai import OpenAI
from starlette.applications import Starlette

from midojo.suites.weather import SYSTEM_MESSAGE

load_dotenv()

LITELLM_API_KEY = os.environ["LITELLM_API_KEY"]
LITELLM_API_URL = os.environ["LITELLM_API_URL"]
LITELLM_MODEL = os.environ["LITELLM_MODEL"]
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8080/mcp")
AGENT_PORT = int(os.environ.get("AGENT_PORT", "8000"))

llm = OpenAI(api_key=LITELLM_API_KEY, base_url=LITELLM_API_URL)


def mcp_tools_to_openai(mcp_tools: list) -> list[dict]:
    """Convert MCP tool definitions to OpenAI function-calling format."""
    openai_tools = []
    for tool in mcp_tools:
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                },
            }
        )
    return openai_tools


async def run_agent_loop(prompt: str) -> str:
    """Connect to MCP, discover tools, run tool-use loop with LLM."""
    async with streamablehttp_client(MCP_SERVER_URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            openai_tools = mcp_tools_to_openai(tools_result.tools)

            messages: list[dict] = [
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": prompt},
            ]

            for _ in range(10):
                response = llm.chat.completions.create(
                    model=LITELLM_MODEL,
                    messages=messages,
                    tools=openai_tools if openai_tools else None,
                )

                choice = response.choices[0]

                if choice.message.tool_calls:
                    messages.append(choice.message.model_dump())

                    for tool_call in choice.message.tool_calls:
                        fn = tool_call.function
                        args = json.loads(fn.arguments) if fn.arguments else {}
                        print(f"  Tool call: {fn.name}({args})")

                        result = await session.call_tool(fn.name, args)
                        content = ""
                        for block in result.content:
                            if hasattr(block, "text"):
                                content += block.text

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": content,
                            }
                        )
                else:
                    return choice.message.content or ""

            return messages[-1].get("content", "") if messages else ""


class WeatherAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_message = context.message
        prompt = ""
        if user_message and user_message.parts:
            prompt = user_message.parts[0].text

        print(f"Received prompt: {prompt[:100]}...")
        response_text = await run_agent_loop(prompt)
        print(f"Response: {response_text[:100]}...")

        await event_queue.enqueue_event(Message(role=Role.ROLE_AGENT, parts=[Part(text=response_text)]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancel not supported")


weather_skill = AgentSkill(
    id="weather_lookup",
    name="Weather Lookup",
    description="Look up current weather conditions for cities",
    tags=["weather"],
    examples=["What's the weather in New York?", "Which city is warmest?"],
)

agent_card = AgentCard(
    name="Weather Agent",
    description="A weather assistant that looks up current conditions using MCP tools.",
    version="1.0.0",
    supported_interfaces=[
        AgentInterface(url=f"http://localhost:{AGENT_PORT}/", protocol_binding="JSONRPC"),
    ],
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[weather_skill],
)

request_handler = DefaultRequestHandler(
    agent_executor=WeatherAgentExecutor(),
    task_store=InMemoryTaskStore(),
    agent_card=agent_card,
)

routes = []
routes.extend(create_agent_card_routes(agent_card))
routes.extend(create_jsonrpc_routes(request_handler, "/"))

app = Starlette(routes=routes)


def main() -> None:
    print(f"Starting A2A weather agent on port {AGENT_PORT}")
    print(f"MCP server: {MCP_SERVER_URL}")
    print(f"LLM model: {LITELLM_MODEL}")
    print(f"Agent card: http://localhost:{AGENT_PORT}/.well-known/agent-card.json")
    uvicorn.run(app, host="127.0.0.1", port=AGENT_PORT)


if __name__ == "__main__":
    main()
