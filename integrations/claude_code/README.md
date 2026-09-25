# MiDojo interceptor for Claude Code

Red-team a **Claude Code agent** by delivering injections through its own tool
loop, with no fake MCP server to write. This is a Claude Code plugin: a
`PostToolUse` hook that reads the active evaluation's injection plan from the
MiDojo control plane, splices any `tool_output` payload into the tool result,
and records the call.

Because Claude Code runs the agent's real tools — `Read`, `Bash`, `Write`, any
connected MCP tool — the hook is the man-in-the-middle for all of them at once.
A suite author writes only a `suite.yaml`: a probe with `channel: tool_output`
and this plugin installed is the entire interception layer.

## Topology

```
                    reads plan, records calls
   ┌───────────────────────────────────────────────┐
   │                                                ▼
Claude Code ──tool call──▶ real tool ──result──▶ PostToolUse hook ──▶ MiDojo
   ▲                                                │              control plane
   └──────────── injected result ◀──────────────────┘
```

Unlike the MCP/PI interception layers, there is no fake server: the agent calls
its real tools, and the hook rewrites the result on the way back. **Do not also
put a fake MCP server in front of a Claude Code agent** — the hook already
intercepts MCP tools (returning `updatedMCPToolOutput`), and two layers would
inject and record the same call twice.

## What it delivers

- **`tool_output` injection.** Every matching instruction in the plan is applied
  to the tool result, in order (`append` / `embed` / `replace` / `new_field`).
  The shared executor is `midojo.injection`.
- **The call trace.** Every tool call is recorded to the control plane. For a
  built-in tool the hook is the *only* recorder, so grading and the
  reachability check see it.
- **Encounter evidence.** The hook records the agent's `transcript_path` as an
  observation, so a later grading pass can confirm the injected text actually
  entered the model's context rather than inferring it from delivery.

It does **not** yet deliver the `memory` or `inter_agent` channels; those arrive
with the Claude Code events that carry them. Argument tampering
(`PreToolUse`) would be a separate `tool_args` channel.

## Install

The plugin lives at this directory. Point Claude Code at it (locally, add it as
a plugin; in a sandbox image, copy it in and enable it). The hook runs
`python3 midojo_hook.py`, which imports `midojo`, so **MiDojo must be installed
in the `python3` the hook invokes** (`pip install midojo` in the sandbox, or the
project venv locally).

Set `MIDOJO_URL` to the control plane (default `http://localhost:8080`). From
inside an OpenShell sandbox that is `http://host.openshell.internal:<port>`, and
the sandbox network policy must allow it — see `example/`.

## Fail-open

Every control-plane call is best-effort. If the control plane is unreachable the
hook returns no modification and exits cleanly: the benchmark degrades to
"injection never delivered" (an honest N/A) rather than breaking the agent.
