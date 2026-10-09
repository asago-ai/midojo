# MiDojo interceptor for Claude Code

Red-team a **Claude Code agent** through its own tool loop — no fake MCP server
to write. This is a Claude Code plugin whose `PostToolUse` hook is the
man-in-the-middle: on every tool call it injects attacker-controlled context the
model reads right after the tool result, and records the delivery for grading.

Because Claude Code runs the agent's real tools (`Read`, `Bash`, `Write`, any
connected MCP tool), one hook intercepts all of them at once — a stronger
demonstration than a per-tool fake server, and the reason the plugin needs no
per-tool code.

## How it works

```
PostToolUse fires (tool_name, tool_output)
  → GET  /agent/environment        (the evaluation's state + injection directives)
  → look up the tool's payload
  → return additionalContext       (the model sees the injected text after the tool result)
  → POST /agent/function-calls      (records real output + injected payload, so grading sees it)
```

**`additionalContext`, not `updatedToolOutput`.** On Claude Code 2.1.x a
PostToolUse hook's `updatedToolOutput` is *not* fed back to the model for
built-in tools — the model still sees the original result, so the injection
never lands. `additionalContext` *is* injected into the model's context, so it
is the vector that actually reaches the agent. It is additive (it appends after
the tool result; it cannot hide the real output), which suits append-style
injections.

The hook authenticates with the evaluation's session token, which MiDojo places
in the sandbox as `MIDOJO_SESSION_TOKEN` (with `MIDOJO_URL`). Every control-plane
call fails open: if the control plane is unreachable the hook injects nothing and
exits cleanly rather than breaking the agent.

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
at evaluation creation, so this reuses MiDojo's existing injection-task
machinery. **This env convention is a deliberate stand-in for a future injection
plan** — when that lands, only the hook's lookup changes. The hook imports
nothing from `midojo`; it speaks only the control plane's `/agent` HTTP contract
via `midojo-sdk`.

## Install

Two forms:

- **As a plugin** (shareable): this directory is a Claude Code plugin
  (`.claude-plugin/plugin.json` + `hooks/hooks.json`).
- **In a sandbox image** (headless, what the demo uses): copy `midojo_hook.py`
  in, install `midojo-sdk`, and declare the `PostToolUse` hook in the agent's
  `~/.claude/settings.json`. See `suites/claude_code_demo/sandbox/`.

The hook's only dependency is `midojo-sdk` (httpx under the hood).
