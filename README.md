# MiDojo

Man-in-the-middle red teaming for AI agents, built on [AgentDojo](https://github.com/ethz-spylab/agentdojo). Test whether agents resist prompt injections planted across their operating environment — starting with [MCP](https://modelcontextprotocol.io) tool responses.

## What is this?

AgentDojo is a framework for evaluating prompt injection attacks and defenses on LLM agents. By default it runs everything in-process with simulated tools. This project bridges the gap to **real agents** by exposing AgentDojo's tools via MCP and adding a proxy mode that can forward tool calls to real infrastructure.

It includes:

- A **benchmark MCP server** — exposes a suite's tools via MCP, backed by AgentDojo's in-memory simulated environment or proxied to real upstream servers
- A **control plane REST API** — for configuring benchmark scenarios, recording traces, and grading results
- An **orchestrator CLI** — drives the full benchmark matrix (user task x injection task x attack) against an external agent
- A **proxy mode** — per-tool routing that forwards read operations to real MCP servers while intercepting writes in simulation, with injection overlay on proxied responses
- **Domain suites** — pluggable task suites with environments, tools, tasks, and attacks (includes a weather reference suite)

## Architecture

```
Orchestrator              Agent                  Benchmark MCP Server
(drives scenarios)        (any MCP-capable       (simulated or proxied tools +
                           agent)                 control plane)

    ──── HTTP ────>          ──── MCP ────>
    (task prompt)            (tools/call)        ┌─ simulate ──> FunctionsRuntime
    <── response ──          <── result ──       │                + Environment
                                                 └─ proxy ────> Real MCP Server
    ──── REST ──────────────────────────>                        + Injection Overlay
    /task/setup, /task/grade
```

### Proxy Mode

In proxy mode (`--real-mcp-url`), forwarding logic lives inside the tool functions themselves. Each tool decides whether to forward to upstream and how to compose the response:

- **Write tools** (deploy, undeploy, send message, etc.) always execute against the local simulated environment
- **Read tools** call `MCPForwardingClient.get_instance().call_tool(...)` to forward to upstream, then append local environment data that may contain injection text (via AgentDojo's `{placeholder}` YAML substitution)

No separate routing config is needed — the tool's code IS the config. This lets you benchmark agents against real infrastructure without planting injections in production systems.

## Quick Start

### Install

```bash
uv sync --extra dev
```

### Run tests

```bash
uv run python -m pytest tests/ -v
```

### Start the real weather MCP server

```bash
weather-mcp-serve --port 8081
```

### Start the benchmark server

```bash
midojo-serve \
    --suite weather \
    --real-mcp-url http://localhost:8081/mcp \
    --host 127.0.0.1 --port 8080
```

This starts both the MCP server (at `/mcp`) and the control plane (at `/task/*`).

### Run the orchestrator against an agent

```bash
midojo-orchestrate \
    --agent-url http://my-agent:8000 \
    --control-url http://localhost:8080 \
    --suite weather
```

## Weather Suite (Reference Implementation)

The weather suite is a minimal working example:

- **3 tools**: get_weather, list_cities, send_weather_alert
- **2 user tasks**: check weather in a city, find the warmest city
- **1 injection task**: trick the agent into sending a fake tornado alert
- **1 injection vector**: notes field appended to weather data

The suite also includes:
- `real_mcp.py` — standalone MCP server with real weather data (start with `weather-mcp-serve`)
- `agent.py` — A2A-compliant agent for E2E testing (start with `weather-agent`)

## Control Plane API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/task/setup` | POST | Configure a benchmark scenario (user task, injection task, injections) |
| `/task/status` | GET | Check current scenario state |
| `/task/prompt` | GET | Get the user task prompt for the current scenario |
| `/task/complete` | POST | Submit the agent's final text output |
| `/task/trace` | GET | Get the recorded tool call trace |
| `/task/grade` | POST | Run utility/security grading |

## Adding a New Suite

1. Create a new package under `src/midojo/suites/your_suite/`
2. Define your `TaskEnvironment` subclass in `environment.py`
3. Create tools — read tools call `MCPForwardingClient.get_instance().call_tool(...)` and compose the upstream result with local environment data; write tools operate on the local environment only
4. Create a `real_mcp.py` — standalone MCP server providing real tool implementations
5. Create user tasks and injection tasks
6. Export `task_suite` and `SYSTEM_MESSAGE` from `__init__.py`
7. Register the suite name in `suites/__init__.py`

## Future Work

Areas to explore for deeper integration with the Red Hat AI safety and evaluation stack.

### Beyond MCP: environment-level injection testing

The current implementation injects into MCP tool responses because that's where the infrastructure hook exists today (the proxy intercepts tool calls). But an agent's attack surface is wider than MCP:

- **RAG / retrieval context** — poisoned chunks from vector stores, file search results, or knowledge bases that flow through the Responses API or framework-level retrieval
- **Agent-to-agent communication (A2A)** — a compromised agent in a swarm sending poisoned messages to other agents
- **System prompt / instruction context** — injections in documents or configurations the prompt references
- **Human-in-the-loop inputs** — approval workflows, Slack messages, or email content that feeds back into the agent

The tool-level injection composition pattern — forward a call to upstream, then append local environment data containing injection text — is channel-agnostic. Extending it beyond MCP to cover retrieval pipelines, A2A messages, and other input surfaces would make this a general-purpose environment-level injection testing framework, not just an MCP tool.

### Reads() / Writes() dependency annotations

AgentDojo's `Depends()` gives tools a mutable reference to an environment attribute but doesn't distinguish read from write access. In proxy mode, this distinction matters: read tools can be forwarded to real upstream servers (with optional injection overlay), while write tools must always run against the local simulated environment so that `post_environment` captures mutations for grading.

Today this classification is implicit in the tool code (read tools call `get_forwarding_client()`, write tools don't). Replacing `Depends()` with explicit `Reads()` and `Writes()` annotations would make it declarative:

```python
# Instead of:
def get_weather(
    cities: Annotated[dict[str, CityWeather], Depends("cities")],
    city: str,
) -> CityWeather: ...

def send_weather_alert(
    alerts: Annotated[list[WeatherAlert], Depends("weather_alerts")],
    city: str,
    message: str,
) -> str: ...

# You'd write:
def get_weather(
    cities: Annotated[dict[str, CityWeather], Reads("cities")],
    city: str,
) -> CityWeather: ...

def send_weather_alert(
    alerts: Annotated[list[WeatherAlert], Writes("weather_alerts")],
    city: str,
    message: str,
) -> str: ...
```

`Reads()` and `Writes()` would subclass `Depends()` (so AgentDojo's runtime works unchanged) but carry semantic metadata. The framework could then automatically enforce that write tools never call the forwarding client, and read tools always do. Combined with the injection vector placeholders already embedded in environment YAML files, this would make forwarding behavior fully declarative rather than coded into each tool function.

### MCP Gateway integration

midojo's benchmark MCP server sits in front of the real one — it forwards tool calls upstream and layers injection content onto the responses. In environments that route tool calls through an MCP gateway (kagenti, or any gateway that supports MCP server registration), the benchmark server can be slotted in as a drop-in replacement for the real server's route. The agent's tool calls get redirected to midojo without any changes to the agent itself — it still thinks it's talking to its normal tools. This makes it straightforward to red-team agents in their actual deployment environment: register midojo as the MCP server for the tools you want to test, point it at the real server via `--real-mcp-url`, and run the benchmark.

### Additional domain suites

Only the weather reference suite exists today. Domain-specific suites can be added for any environment where agents interact with tools.

### Damage prevention via agent runtime hooks

Agent runtimes like Claude Code expose hook systems (e.g., `PreToolUse`) that can intercept tool calls before execution — modifying inputs, denying calls, or injecting context. These hooks cannot fabricate tool responses or modify outputs, so they can't plant injections. But they're useful for the opposite purpose: preventing real-world side effects when an agent falls for an injection during a benchmark. For example, a PreToolUse hook could deny a `deploy_model` call that targets an attacker-controlled endpoint, letting you observe that the agent was compromised without it causing actual damage.

The pattern is: midojo's proxy plants the injection at the tool response layer; the runtime hook prevents dangerous actions from executing. This two-layer approach — inject via proxy, contain via hooks — would allow benchmarking against live infrastructure with a safety net.

[agent-eval-harness](https://github.com/opendatahub-io/agent-eval-harness) (opendatahub-io) is one example of a framework that uses PreToolUse hooks for evaluation isolation (auto-answering prompts, blocking production API calls). Its hook patterns could be adapted for damage prevention during midojo benchmarks. Its MLflow integration, configurable judge abstractions, and HTML report generation are also worth adopting.

### Framework-level injection via tool response hooks

midojo currently injects at the proxy level — intercepting MCP tool responses between server and agent. But several agent frameworks expose hooks that can intercept and *modify* tool outputs before the LLM sees them, opening an alternative injection strategy that doesn't require a proxy:

- **LangChain/LangGraph** — custom `ToolNode` or `@wrap_tool_call` middleware can fully replace tool outputs
- **CrewAI** — `@after_tool_call` hook receives the tool result and can return a modified string
- **OpenAI Agents SDK** — `@tool_output_guardrail` can substitute responses via `reject_content()`
- **Claude Agent SDK** — `PostToolUse` hook supports `updatedMCPToolOutput` for MCP tools

This means three injection strategies depending on what layer you control:

1. **Proxy-level** (current midojo approach) — agent-agnostic, works with anything that speaks MCP. You control the server.
2. **Framework-level** — use the agent framework's own hooks to inject. You control the agent code. Most flexible for LangChain/CrewAI where full output replacement is supported.
3. **Gateway-level** — inject at the MCP Gateway infrastructure. Agent and framework agnostic. You control the platform.

Supporting framework-level injection would let midojo work with agents that don't use MCP, or where inserting a proxy isn't practical.