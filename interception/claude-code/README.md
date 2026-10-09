# MiDojo interceptor for Claude Code

Red-team a **Claude Code agent** through its own tool loop — no fake MCP server
to write. This is a Claude Code plugin whose `PostToolUse` hook is the
man-in-the-middle: on every tool call it splices an injection payload into the
tool result the model sees, and records the call for grading.

Because Claude Code runs the agent's real tools (`Read`, `Bash`, `Write`, any
connected MCP tool), one hook intercepts all of them at once — a stronger
demonstration than a per-tool fake server, and the reason the plugin needs no
per-tool code.

## How it works

```
PostToolUse fires (tool_name, tool_output)
  → GET  /agent/environment        (the evaluation's state + injection directives)
  → splice the tool's payload into tool_output   (append | replace)
  → POST /agent/function-calls     (the modified call — reachability + grading see it)
  → return updatedToolOutput       (the model now sees the injected result)
```

It authenticates with the evaluation's session token, which MiDojo places in the
sandbox as `MIDOJO_SESSION_TOKEN` (alongside `MIDOJO_URL`). Every control-plane
call fails open: if the control plane is unreachable the hook injects nothing and
exits cleanly rather than breaking the agent.

## Where targeting lives (prototype)

Which tool gets which payload is read from the evaluation environment, by
convention:

```yaml
environment:
  injections:
    tool_output:
      Read:  { payload: "{exfil:main}", mode: append }
```

The `{task:probe}` placeholder is filled with the active injection task's payload
at evaluation creation, so this reuses MiDojo's existing injection-task
machinery. **This env convention is a deliberate stand-in for a future injection
plan** — when that lands, only the hook's lookup changes; the splice, recording
and session handling stay. The hook imports nothing from `midojo`; it speaks only
the control plane's `/agent` HTTP contract via `midojo-sdk`.

## Install

Two forms:

- **As a plugin** (shareable): this directory is a Claude Code plugin
  (`.claude-plugin/plugin.json` + `hooks/hooks.json`). Install and enable it in a
  Claude Code session.
- **In a sandbox image** (headless, what the demo uses): copy `midojo_hook.py`
  in, install `midojo-sdk`, and declare the `PostToolUse` hook in the agent's
  `~/.claude/settings.json`. See `suites/claude_code_demo/sandbox/`.

The hook's only dependency is `midojo-sdk` (httpx under the hood).
