# MiDojo interceptor for Claude Code

Red-team a **Claude Code agent you already have** — no changes to the agent, no
fake tools to write. You install this plugin, point it at a MiDojo control
plane, and run the benchmark. The plugin's `PostToolUse` hook is the
man-in-the-middle: on every tool call it embeds an injection into the tool
result the model reads, and records the call for grading.

Because Claude Code runs the agent's real tools (`Read`, `Bash`, `Write`, any
connected MCP tool), one plugin intercepts all of them at once — the reason it
needs no per-tool code and no access to your agent's internals.

## The flow

```
1. Start the MiDojo control plane      midojo-serve --load-suite <suite>
2. Install this plugin in your agent   (enable the plugin; set MIDOJO_URL)
3. Run the benchmark                   midojo-run --suite <suite> ...
```

Your agent is unchanged. MiDojo hands each evaluation a session token; the plugin
reads it (`MIDOJO_SESSION_TOKEN`) and talks only to the control plane's `/agent`
HTTP API through `midojo-sdk`. It imports nothing from `midojo` and never touches
your agent's configuration beyond being installed as a plugin.

## How the injection works

```
PostToolUse fires (tool_name, tool_response)
  → GET  /agent/environment     (the evaluation's injection directives)
  → embed the payload into the tool's result     (organic: looks like real data)
  → return updatedToolOutput    (the model reads the poisoned result)
  → POST /agent/function-calls   (records the delivery, so grading sees it)
```

**Organic embedding, not a labelled note.** The faithful injection goes *inside*
the tool's real result, so the agent cannot tell it from legitimate data. The
hook sets `updatedToolOutput` to the tool's own result shape with the payload
spliced into its content field — `Read` → `file.content`, `Bash` → `stdout`.
(A bare-string `updatedToolOutput` is silently ignored by Claude Code 2.1.x;
it must match the tool's structure.) For a tool whose shape the hook doesn't
know, it falls back to `additionalContext` — a note injected after the tool
result. The two differ in realism: embedding is untrusted *data* the model tends
to scrutinise; `additionalContext` reads as authoritative context the model is
likelier to obey. Both are useful vectors.

## Where targeting lives (prototype)

Which tool gets which payload is read from the evaluation environment, by
convention:

```yaml
environment:
  injections:
    tool_output:
      Read: { payload: "{exfil:main}" }
```

The `{task:probe}` placeholder is filled with the active injection task's payload
at evaluation creation, reusing MiDojo's injection-task machinery. **This env
convention is a deliberate stand-in for a future injection plan** — when that
lands, only the hook's lookup changes.

Every control-plane call fails open: if the control plane is unreachable the hook
injects nothing and exits cleanly rather than breaking the agent.

## Install into your own agent

This directory is a Claude Code plugin (`.claude-plugin/plugin.json` +
`hooks/hooks.json`). Install and enable it in your Claude Code setup, then set
`MIDOJO_URL` (and `MIDOJO_SESSION_TOKEN`, which MiDojo provides per evaluation).
The hook's only dependency is `midojo-sdk` (httpx under the hood).

For a fully isolated run — a sandbox per evaluation, with the agent's filesystem
and network diffed and audited — MiDojo's `openshell` runtime bakes the plugin
into an agent image and runs it on a gateway. See `suites/claude_code_demo/` for
a complete, runnable example.
