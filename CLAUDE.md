# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

midojo is a generic framework for running [AgentDojo](https://github.com/ethz-spylab/agentdojo) prompt injection benchmarks against real agents via MCP. It separates the benchmark framework (MCP server, control plane, orchestrator, proxy) from domain-specific task suites.

The project depends on AgentDojo (the core benchmarking framework) and adds:
- A benchmark MCP server (FastMCP) that wraps AgentDojo's FunctionsRuntime
- A FastAPI control plane for scenario management and grading
- An orchestrator CLI for driving benchmarks against external agents
- A proxy mode that forwards tool calls to real MCP servers with injection overlay
- Domain suites with simulated environments, tools, tasks, and attacks

## Key Commands

### Setup
```bash
# Install all dependencies
uv sync --extra dev
```

### Testing
```bash
# Run all tests
uv run python -m pytest tests/ -v

# Run specific test files
uv run python -m pytest tests/test_mcp_server.py
uv run python -m pytest tests/test_control_api.py
uv run python -m pytest tests/test_grading.py
uv run python -m pytest tests/test_suite_check.py
uv run python -m pytest tests/test_proxy.py
```

### Linting
```bash
uv run ruff check --fix .
uv run ruff format
```

### Running
```bash
# Start the real weather MCP server (provides actual tool implementations)
weather-mcp-serve --port 8081

# Start benchmark MCP server + control plane (forwards reads to real server)
midojo-serve --suite weather --real-mcp-url http://localhost:8081/mcp

# Run benchmarks against an external agent
midojo-run --agent-url http://agent:8000 --protocol a2a --suite weather
```

## Code Architecture

### Framework Layer (`src/midojo/`)

- `app/routers/mcp.py` — `create_mcp_server()`, `_make_tool_handler()`. Dynamically registers tools from AgentDojo `Function` objects into FastMCP, building wrapper functions with correct signatures (excluding Depends-injected params). Uses `asyncio.to_thread` when a forwarding client is configured.
- `app/routers/tasks.py` — FastAPI router with `/task/setup`, `/task/status`, `/task/prompt`, `/task/complete`, `/task/trace`, `/task/grade` endpoints.
- `app/models.py` — `BenchmarkSession[Env]`, `SessionHolder`, `TraceEntry`, request/response models.
- `grading.py` — `grade_task()` wrapping TaskSuite's `_check_task_result()` for utility and security evaluation. Generic over `TaskEnvironment`.
- `serve.py` — combines MCP server (streamable HTTP at `/mcp`) and FastAPI control plane into one FastAPI app. Requires `--suite` and `--real-mcp-url`. Runs a preflight check at startup reporting each task's validity and injectability.
- `forwarding.py` — `MCPForwardingClient` (sync `call_tool` wrapping async MCP client), class-level singleton (`initialize()`, `get_instance()`, `is_initialized()`, `_reset()`). Initialized at startup from `--real-mcp-url`.
- `orchestrator.py` — Click CLI (`midojo-run`) that drives the benchmark matrix against external agents. `--protocol` is required (`http` or `a2a`). Non-injectable user tasks show N/A for security and are excluded from the security average.
- `agent_client.py` — `AgentClient` ABC with `SimpleHTTPAgentClient` and `A2AAgentClient` implementations. `SimpleHTTPAgentClient` raises `ValueError` if the response JSON has no recognized key.

### Suite Layer (`src/midojo/suites/`)

- `__init__.py` — Suite registry: `get_suite(name)`, `list_suites()`
- `weather/` — Weather domain suite (reference implementation):
  - `real_mcp.py` — Standalone MCP server with real weather tool implementations
  - `agent.py` — A2A weather agent (connects to benchmark MCP, uses LLM for reasoning)
  - `environment.py` — Pydantic models (CityWeather, WeatherAlert, WeatherEnvironment)
  - `tools.py` — 3 benchmark tool functions (get_weather, list_cities, send_weather_alert)
  - `task_suite.py` — creates `TaskSuite[WeatherEnvironment]`
  - `user_tasks.py` — 3 user tasks (2 injectable, 1 not)
  - `injection_tasks.py` — 1 injection task
  - `data/` — YAML fixtures for the environment and injection vectors

### Key Design Patterns

- **Dynamic tool registration**: MCP tool handlers are generated at startup from AgentDojo `Function.parameters` Pydantic models. The `__signature__` is set on each handler so FastMCP infers the correct JSON Schema, excluding Depends-injected environment params.
- **Session-based state**: A `SessionHolder` is shared between the MCP server and control API. The control API manages the lifecycle (setup/complete), the MCP server mutates the environment on tool calls.
- **Trace recording**: Every tool call is recorded as a `TraceEntry` (function, args, result, error, timestamp) for trace-based grading via `utility_from_traces` / `security_from_traces`.
- **Tool-level forwarding**: Forwarding logic lives inside tool functions, not in external config. Read tools call `MCPForwardingClient.get_instance().call_tool(...)` and compose the upstream result with local environment data (which may contain injection text via AgentDojo's `format(**injections)` YAML substitution). Write tools always operate on the local simulated environment. No separate routing config, injection vector map, or overlay logic needed.
- **Security convention**: `security=True` in grading results means the attack **succeeded** (matching AgentDojo's convention where this maps to "Attack Success Rate").

## Task Registration

User tasks and injection tasks register themselves via decorators when their modules are imported. Several modules import task modules to trigger this registration. This is intentional — do not remove these imports even though they appear unused.

## Code Style

- Modern Python typing (3.10+): `list[str]`, `dict[str, int]`, `str | None`
- Module-level imports only, no local imports inside functions
- Ruff for linting (line-length=120, rules: F, UP, I, ERA, N, RUF)
- Pyright for type checking (basic mode)
