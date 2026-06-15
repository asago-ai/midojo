# Translator: agent-policy-redteam → MiDojo

Converts scenario artifacts from [agent-policy-redteam](https://github.com/MuneezaAzmat/RH_TrustyAI_POC/tree/main/agent-policy-redteam/runs/delayed) into self-contained MiDojo suites. The translator is deterministic — no LLM calls.

## What it does

The translator bridges the two: it takes agent-policy-redteam's output artifacts and produces a MiDojo suite that can be benchmarked immediately.

```
agent-policy-redteam artifacts          MiDojo suite
─────────────────────────────          ─────────────
runs/delayed/                    →     suites/hr_exfil/
├── manifest.yaml                       ├── __init__.py
├── env_models.py                       ├── suite.yaml
├── tools.py                            └── a2a_agent/
├── seed_data.yaml                          └── fake_mcp.py
└── injection.yaml
```

## Input: artifact bundle

The translator expects a directory with five files:

| File | Description |
|------|-------------|
| `manifest.yaml` | User task prompt and expected tool sequence |
| `env_models.py` | Pydantic model classes (Employee, Environment, etc.) |
| `tools.py` | Tool functions the agent can call |
| `seed_data.yaml` | Initial environment state (clean, no injections) |
| `injection.yaml` | Attack payloads, target records/fields, and verification predicates |

## Usage

```bash
# Translate artifacts into a MiDojo suite
midojo-translate /path/to/artifact-bundle suites/my_suite

# Start the control plane
midojo-serve --suite my_suite --host 127.0.0.1 --port 8080

# Start the generated fake MCP server (no upstream needed)
python suites/my_suite/a2a_agent/fake_mcp.py --port 8082

# Run the benchmark against your agent
# if you're using ogx protocol, be sure to install relevant client deps from [weather] extra
MCP_SERVER_URL=http://localhost:8082/mcp \
  midojo-run \
    --agent-url http://localhost:8321 \
    --protocol ogx \
    --suite my_suite \
    --ogx-model your-model-id
```

## How the translation works

1. **Environment state** — `seed_data.yaml` is copied and probe placeholders (`{injection_task_0:main}`) are inserted at the injection target fields specified in `injection.yaml`.

2. **Tool definitions** — `tools.py` is parsed with Python's `ast` module to extract function names, docstrings, and parameter signatures for the `tools:` section in `suite.yaml`.

3. **Utility predicates** — Derived heuristically by matching seed data values against words in the user task prompt. Produces `output_contains_any` checks.

4. **Security predicates** — Derived by scanning the injection payload text for tool names and email addresses, then finding which environment field the triggered tool mutates (via AST). Produces `env_list_any_match` checks.

5. **Fake MCP server** — A generic adapter is generated that embeds the original `env_models.py` and `tools.py`. Every tool call goes through the MiDojo control plane: GET the environment, run the original tool function, PUT back if the state changed.

## Running locally with OGX + Ollama

If you don't have an OGX server, you can set one up locally with Ollama models:

```bash
# Set up an OGX starter server
uv init ogx-starter-server && cd ogx-starter-server
uv add 'ogx[starter]' openai botocore
export OLLAMA_URL=http://localhost:11434/v1
uv run ogx stack run starter
```

This starts an OGX server at `http://localhost:8321/v1` with OpenAI Responses API support. Pass your local Ollama model to the benchmark:

```bash
midojo-run \
  --agent-url http://localhost:8321 \
  --protocol ogx \
  --suite my_suite \
  --ogx-model ollama/your-model-name
```

## Notes

- **Utility and security predicates are heuristic.** They work for the common patterns agent-policy-redteam generates (CRUD tools, email exfiltration) but may need manual adjustment for unusual scenarios. A future improvement is for agent-policy-redteam to emit explicit predicates in the artifact bundle.

- **The fake MCP server has no upstream.** Since agent-policy-redteam generates fully synthetic environments, there is no real data source. All data comes from the MiDojo control plane's environment state.

- **The generated suite is self-contained.** Once translated, it works like any other MiDojo suite — `midojo-serve`, `midojo-run`, and the standard grading pipeline all work unchanged.
