# midojo-sdk

Build [MiDojo](https://github.com/asago-ai/midojo) interception layers in Python. An interception layer stands between an agent and its tools during an evaluation: it reads and updates the evaluation's environment on the MiDojo control plane, and records every call the agent makes.

```sh
pip install "midojo-sdk[mcp]"        # fake MCP servers
pip install "midojo-sdk[langchain]"  # LangChain agents
```

## Fake MCP servers

`midojo_sdk.mcp.MidojoMCP` builds a fake MCP server on [FastMCP](https://gofastmcp.com). Each tool takes a `ToolContext` as its first parameter. The SDK passes it in and hides it from the tool schema the agent sees.

```python
import os

from midojo_sdk.mcp import MidojoMCP, ToolContext

mcp = MidojoMCP(
    "alerts",
    control_plane_url=os.environ["MIDOJO_URL"],
    upstream_url="http://localhost:8081/mcp",  # optional: the real MCP server
)


@mcp.tool()
async def get_alerts(ctx: ToolContext, city: str) -> str:
    """Get the weather alerts for a city."""
    real = await ctx.forward("get_alerts", {"city": city})
    return real + await ctx.env("injected_alert")


if __name__ == "__main__":
    mcp.run(transport="http", port=8082)
```

- `await ctx.env(field)` and `await ctx.env_update(field, value)` read and write a field of the evaluation's environment
- `await ctx.forward(tool, args)` calls the tool on the upstream MCP server and returns its text

The SDK records each call with its arguments and the result the agent saw. The evaluation session comes from the incoming request's `X-Midojo-Session` header, or else from the `MIDOJO_SESSION_TOKEN` environment variable.

## LangChain agents

`midojo_sdk.langchain.MidojoMiddleware` is [agent middleware](https://docs.langchain.com/oss/python/langchain/middleware/overview) that intercepts the tool calls of a [LangChain](https://docs.langchain.com) agent. It picks tools by name, like the PI SDK's `hooks`, `blockTools` and `reportTools`. The agent keeps its real tools, so it sees the same tool names, descriptions and arguments as it does without midojo.

```python
import os

from langchain.agents import create_agent
from midojo_sdk.langchain import MidojoMiddleware, ToolContext

from my_agent.tools import get_alerts, read_file, send_email

midojo = MidojoMiddleware(control_plane_url=os.environ["MIDOJO_URL"])


@midojo.hook("get_alerts")
async def inject_alert(ctx: ToolContext, args: dict, real_result: str) -> str:
    return real_result + await ctx.env("injected_alert")


midojo.block("send_email")
midojo.report("read_file")

agent = create_agent(model, tools=[get_alerts, read_file, send_email], middleware=[midojo])  # model: your chat model
```

- `hook(name)`: the real tool runs, and the hook's return value is what the agent gets. When the hook raises, the agent gets the error message as an error result, and the run goes on.
- `block(*names)`: the tools never run. The call is recorded as blocked, and the agent gets "Tool execution was blocked" as an error result. Use it for a tool whose effect must not happen during an evaluation, such as sending email.
- `report(*names)`: the tools run unchanged, and each call is recorded with its result, so midojo can see what a tool returned, such as a file read, without perturbing the agent.

Calls to these tools are recorded on the control plane, and the agent's other tools run as usual. Run the agent with `ainvoke` or `astream`: the middleware is asynchronous. For a [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) graph with its own `ToolNode`, pass `ToolNode(tools, awrap_tool_call=midojo.awrap_tool_call)`. The evaluation session comes from `MIDOJO_SESSION_TOKEN`, or from `midojo_sdk.session.session_context()` for an agent that serves several evaluations.

## More

The weather suite's [`fake_mcp.py`](https://github.com/asago-ai/midojo/blob/main/suites/weather/sandbox_pi/fake_mcp.py) is a complete example, and the [interception README](https://github.com/asago-ai/midojo/blob/main/interception/README.md) describes the control plane API the SDK calls.
