# Interception SDKs

An interception layer sits between an agent and its tools during an evaluation. It decides what the agent's tool calls return, which is where MiDojo places injections, and it reports every call to the MiDojo control plane so verifiers can grade the run. Suite authors build one per agent with an SDK:

| SDK | Package | Intercepts |
|---|---|---|
| [`pi-sdk/`](pi-sdk/) | `@midojo/pi-sdk` (npm) | the tools of a [PI](https://pi.dev) coding agent, as a PI extension |
| [`python-sdk/`](python-sdk/) | `midojo-sdk` (PyPI) | an MCP server, as a fake MCP server built on FastMCP (`midojo_sdk.mcp`) |
| [`python-sdk/`](python-sdk/) | `midojo-sdk` (PyPI) | the tool calls of a [LangChain](https://docs.langchain.com) agent, as agent middleware (`midojo_sdk.langchain`) |

The SDKs depend only on the control plane's HTTP API, described below, and not on the `midojo` package. An SDK for another framework or language implements the same calls.

## The evaluation session

The control plane issues a session token for each evaluation. An interception layer sends it on every call as `Authorization: Bearer <token>`, and the token selects the evaluation's environment and call record. How the layer gets the token depends on how MiDojo reaches the agent:

- The `openshell` runtime sets `MIDOJO_SESSION_TOKEN` and `MIDOJO_URL` (the control plane URL) in the sandbox's environment. Both SDKs read them.
- For an `unmanaged` agent, `midojo-run` sends the token in the `X-Midojo-Session` request header. `midojo_sdk.mcp` reads the header from the incoming MCP request, and `midojo_sdk.session` has helpers for agents that pass it on to their own tool servers.

## Control plane API

All paths are relative to the control plane URL and take the session's bearer token.

| Call | Body | Returns |
|---|---|---|
| `GET /agent/environment` | | the evaluation's environment, as JSON |
| `PUT /agent/environment` | the whole environment | the stored environment. The control plane validates it against the suite's environment schema |
| `POST /agent/function-calls` | `{"function", "args", "result", "error", "blocked"}` | the recorded call (201) |
| `GET /agent/function-calls` | | the calls recorded so far |

In a function-call record, `result` is what the agent saw. `error` (optional) is the error the tool raised. `blocked` (default `false`) means the tool never ran and `result` is what the agent was told instead.
