# Interception SDKs

An interception layer sits between an agent and its tools during an evaluation. It decides what the agent's tool calls return, which is where MiDojo places injections, and it reports every call to the MiDojo control plane so verifiers can grade the run. Suite authors build one per agent with an SDK:

| SDK | Package | Intercepts |
|---|---|---|
| [`pi-sdk/`](pi-sdk/) | `@midojo/pi-sdk` (npm) | the tools of a [PI](https://pi.dev) coding agent, as a PI extension |
| [`python-sdk/`](python-sdk/) | `midojo-sdk` (PyPI) | an MCP server, as a fake MCP server built on FastMCP (`midojo_sdk.mcp`) |
| [`python-sdk/`](python-sdk/) | `midojo-sdk` (PyPI) | the tool calls of a [LangChain](https://docs.langchain.com) agent, as agent middleware (`midojo_sdk.langchain`) |

The SDKs depend only on the control plane's HTTP API, described below, and not on the `midojo` package. An SDK for another framework or language implements the same calls.

## How the SDKs intercept tools

The SDKs intercept tools the same way, so a suite's evaluation means the same thing whichever agent it targets. An SDK for another framework follows the same rules:

- **The agent keeps its real tools.** An SDK attaches to the agent's tools by name instead of replacing them, so the agent sees the same tool names, descriptions and arguments as it does without MiDojo. Only a tool the agent doesn't have, such as a fake notification tool a suite adds, gets its own definition.
- **A tool is hooked, blocked or reported:**
  - *hook*: the real tool runs, and the hook's return value is what the agent gets. The hook can read and update the evaluation's environment.
  - *block*: the tool never runs, and the agent gets `Tool execution was blocked` as an error result. Use it for a tool whose effect must not happen during an evaluation, such as sending email.
  - *report*: the tool runs, and the agent gets its result unchanged.
- **Every intercepted call is recorded once,** with `POST /agent/function-calls`: the agent's arguments, the result the agent saw, the error if there was one, and whether the call was blocked. Tools that aren't intercepted run as usual and aren't recorded.
- **Errors don't end the run.** When a hook raises, the call is recorded with the error, and the agent gets the message as an error result. The agent carries on as it would after any failed tool call.
- **No session, no call.** An intercepted call needs the evaluation's session. Without one, the SDK raises an error instead of letting the call go unrecorded.

Where each SDK stands:

| | PI (`@midojo/pi-sdk`) | LangChain (`midojo_sdk.langchain`) | MCP (`midojo_sdk.mcp`) |
|---|---|---|---|
| The agent keeps its real tools | yes | yes | no: the fake server defines each tool again, and `ctx.forward` calls the real one |
| Hook, block, report | `hooks`, `blockTools`, `reportTools` | `hook`, `block`, `report` | no: each tool is a fake that can forward to the real one |
| Errors come back as error results | no: a hook's or fake tool's error reaches the agent as plain text | yes | yes |
| Report records the tool's error | no: it always records `error: null` | yes | no report |

## The evaluation session

The control plane issues a session token for each evaluation. An interception layer sends it on every call as `Authorization: Bearer <token>`, and the token selects the evaluation's environment and call record. How the layer gets the token depends on how MiDojo reaches the agent:

- The `openshell` runtime sets `MIDOJO_SESSION_TOKEN` and `MIDOJO_URL` (the control plane URL) in the sandbox's environment. The SDKs read them.
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
