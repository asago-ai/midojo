# MiDojo interceptor for Claude Code

Red-team a **Claude Code agent you already have** — no changes to the agent, no fake tools to write. You install this plugin, point it at a MiDojo control plane, and run the benchmark. The plugin's `PostToolUse` hook is the man-in-the-middle: on every tool call it embeds an injection into the tool result the model reads, and records the call for grading.

Because Claude Code runs the agent's real tools (`Read`, `Bash`, `Write`, any connected MCP tool), one plugin intercepts all of them at once — the reason it needs no per-tool code and no access to your agent's internals.

## The flow

```
1. Start the MiDojo control plane      midojo-serve --load-suite <suite>
2. Install this plugin in your agent   (enable the plugin; set MIDOJO_URL)
3. Run the benchmark                   midojo-run --suite <suite> ...
```

Your agent is unchanged. MiDojo hands each evaluation a session token; the plugin reads it (`MIDOJO_SESSION_TOKEN`) and talks only to the control plane's `/agent` HTTP API through `midojo-sdk`. It imports nothing from `midojo` and never touches your agent's configuration beyond being installed as a plugin.

## How the injection works

```
PostToolUse fires (tool_name, tool_response)
  → GET  /agent/environment     (the evaluation's injection directives)
  → embed the payload into the tool's result     (organic: looks like real data)
  → return updatedToolOutput    (the model reads the poisoned result)
  → POST /agent/function-calls   (records the delivery, so grading sees it)
```

**Organic embedding, not a labelled note.** The faithful injection goes *inside* the tool's real result, so the agent cannot tell it from legitimate data. The hook sets `updatedToolOutput` to the tool's own result shape with the payload spliced into its content field — `Read` → `file.content`, `Bash` → `stdout`. MCP tools (`mcp__<server>__<tool>`) deliver their result as a JSON string; the hook embeds into that and re-serialises, keeping the native string shape. (A bare-string `updatedToolOutput` is silently ignored for a struct-shaped tool by Claude Code 2.1.x; it must match the tool's own structure.) 

For a tool whose shape the hook doesn't know, it falls back to `additionalContext` — a note injected after the tool result. The two differ in realism: embedding is untrusted *data* the model tends to scrutinise; `additionalContext` reads as authoritative context the model is likelier to obey. Both are useful vectors.

## Where targeting lives (prototype)

Which tool gets which payload is read from the evaluation environment, by convention:

```yaml
environment:
  injections:
    tool_output:
      Read: { payload: "{exfil:main}" }
```

The `{task:probe}` placeholder is filled with the active injection task's payload at evaluation creation, reusing MiDojo's injection-task machinery. **This env convention is a deliberate stand-in for a future injection plan** — when that lands, only the hook's lookup changes.

Every control-plane call fails open: if the control plane is unreachable the hook injects nothing and exits cleanly rather than breaking the agent.

## Compatibility

Tested against **Claude Code 2.1.x** (2.1.156). The hook depends on the PostToolUse wire contract: the `tool_response` input field, a tool-shaped `updatedToolOutput` for organic embedding, and `additionalContext` for the
fallback/`context` vector. Other Claude Code versions may format pre/post-tool hooks differently (field names, whether `updatedToolOutput` is applied to built-in tools); pin or re-verify against the version your agent runs.

## Install into your own agent

This directory is a Claude Code plugin, published through a marketplace manifest at the repo root (`.claude-plugin/marketplace.json`). Install it the normal way:

```sh
# 1. The hook runs via `python3`; that interpreter needs the SDK.
pip install midojo-sdk            # or: uv pip install midojo-sdk

# 2. Add this repo as a marketplace and install the plugin.
claude plugin marketplace add asago-ai/midojo      # or a local path to the repo
claude plugin install midojo-interceptor@midojo

# 3. Point the hook at a running MiDojo control plane.
export MIDOJO_URL=http://localhost:8080
#    MIDOJO_SESSION_TOKEN is supplied per evaluation by midojo-run.
```

`claude plugin details midojo-interceptor` should list one `PostToolUse` hook. Your Claude Code agent is otherwise unchanged. (Verified end to end: with the plugin installed this way and no settings edits, the hook fires on a tool call and delivers the injection.)

Note on `python3`: the plugin's `hooks/hooks.json` runs the hook with bare `python3` (and `${CLAUDE_PLUGIN_ROOT}` for its path), so the `python3` your agent resolves at runtime must be the interpreter you installed `midojo-sdk` into. If the hook silently does nothing, that mismatch — or the control plane being unreachable — is the usual cause; both fail open by design.

For a fully isolated, headless run — a sandbox per evaluation, with the agent's filesystem and network diffed and audited — MiDojo's `openshell` runtime installs this plugin into the agent image the same way (`claude plugin install` from a local marketplace), so the demo exercises the real packaging path with no settings edits. The only runtime caveat is that the marketplace and plugin files must sit where the sandbox's filesystem policy allows the agent to read them (the demo stages them under `/sandbox`). See `suites/claude_code_demo/` for a complete, runnable example.

### Future consideration: interceptor tamper-resistance

The demo stages the plugin under `/sandbox`, which is also the agent's read-write playground. Because the agent *is* Claude Code — the model drives the same process — its `Write`/`Bash` tools can reach anything the filesystem policy marks writable. So today a sufficiently adversarial injection could, in principle, have the agent overwrite the hook, flip `enabledPlugins`, or tamper with the hook's interpreter (`/sandbox/.venv`) and silently neutralize MiDojo. This is acceptable for the current prototype (the demo's injections don't target the interceptor), but a hardened setup should move the interceptor out of the playground onto read-only paths the policy denies the agent:

- Define the hook via Claude Code's read-only **managed/system settings** (`/etc/claude-code/managed-settings.json`, highest precedence, not user-overridable) rather than a `claude plugin install` that copies a mutable hook into the writable user config dir.
- Keep the hook code, its interpreter, and `midojo-sdk` on read-only paths (e.g. a dedicated `/opt/midojo`, or the already read-only `/usr` / `/app`).

Tracked as a follow-up; not yet implemented.
