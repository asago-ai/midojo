# midojo-sdk

Build [MiDojo](https://github.com/asago-ai/midojo) interception layers in Python. An interception layer stands between an agent and its tools during an evaluation: it reads and updates the evaluation's environment on the MiDojo control plane, and records every call the agent makes.

```sh
pip install "midojo-sdk[mcp]"
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

The weather suite's [`fake_mcp.py`](https://github.com/asago-ai/midojo/blob/main/suites/weather/sandbox_pi/fake_mcp.py) is a complete example, and the [interception README](https://github.com/asago-ai/midojo/blob/main/interception/README.md) describes the control plane API the SDK calls.
