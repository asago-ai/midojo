# Minibank Suite

A banking-domain red-team suite for MiDojo with 12 MCP tools, 4 user tasks,
and 5 injection tasks targeting fund transfers, PII exfiltration, compliance
bypass, and privilege abuse.

## Structure

```
suites/minibank/
├── __init__.py              # SYSTEM_MESSAGE for the agent
├── suite.yaml               # Environment, probes, tasks, and predicates
├── README.md                # This file
├── real_environment/        # Simulates a customer's existing backend (see below)
│   ├── bank_state.py        # In-memory bank: customers, accounts, transactions
│   ├── bank_tools.py        # Safe tool executor (business rules enforced)
│   └── bank_tools_unsafe.py # Unsafe executor (rules removed, for red-team demos)
└── a2a_agent/
    ├── fake_mcp.py          # MiDojo interception layer (what suite authors write)
    ├── real_mcp.py          # Upstream MCP server wrapping real_environment
    └── agent.py             # A2A agent for E2E testing
```

## About `real_environment/`

In a real adoption scenario, the customer already has their banking backend and
MCP server -- they don't need to write these modules. The files in
`real_environment/` simulate what would already exist outside the MiDojo repo:

- `bank_state.py` -- the customer's data layer (accounts, transactions, etc.)
- `bank_tools.py` -- the customer's business logic (dual-auth, sanctions, PII audit)
- `bank_tools_unsafe.py` -- a variant with safety rules removed (for demonstrating
  what happens when an agent bypasses controls)

A MiDojo suite author only needs to write `fake_mcp.py` + `suite.yaml`. The
`real_environment/` is included here so the suite is fully self-contained and
runnable without an external service.

This contrasts with the simpler weather suite, where `real_mcp.py` has hardcoded
data and no separate backend. The minibank suite demonstrates the more realistic
pattern where MiDojo integrates with an existing complex backend.

## Running

Follow the same pattern as the weather suite (see main README):

```bash
minibank-real-mcp-serve --port 8083
midojo-serve --suite minibank --host 127.0.0.1 --port 8080
minibank-fake-mcp-serve --port 8082 --upstream-url http://localhost:8083/mcp
midojo-run --agent-url http://localhost:8000 --protocol a2a --suite minibank
```
