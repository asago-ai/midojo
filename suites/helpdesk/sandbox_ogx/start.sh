#!/bin/sh
# Starts the helpdesk deployment inside the sandbox, then runs the command
# passed as arguments (the helpdesk application with the user's message):
#
#   moderation_*.py :8322 guardrail adapter: HELPDESK_GUARD=local (default,
#                         ProtectAI's classifier in the sandbox) or remote (a
#                         guard model on the model server)
#   fake_mcp.py    :8765  MiDojo's fake helpdesk MCP server
#   ogx            :8321  OGX server: Responses API, server-side tool loop
#   praxis-ai      :8080  or, with HELPDESK_GATEWAY=praxis, Praxis AI instead
#                         (sandbox_praxis/): the same tool loop as a gateway
#
# Each server logs to /tmp so it doesn't hold the agent's output open.
set -e
PY=/sandbox/helpdesk/.venv/bin/python
# Cached in the image: the sandbox blocks downloads.
export TIKTOKEN_CACHE_DIR=/sandbox/helpdesk/tiktoken
export HF_HOME=/sandbox/helpdesk/hf HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
cd /sandbox/helpdesk
mkdir -p /tmp/ogx

# About 10s after the sandbox loads its network policy, OpenShell's first
# settings poll bumps the policy generation: connections and DNS mappings made
# before it stop working. OGX's model client retries and resolves again;
# Praxis AI resolves the model server once, at startup, and keeps the dead
# address. Start the servers after that point.
age=$(ps -o etimes= -p 1 | tr -d ' ')
if [ "${age:-0}" -lt 15 ]; then sleep $((15 - age)); fi

"$PY" "moderation_${HELPDESK_GUARD:-local}.py" 8322 </dev/null >/tmp/moderation.out 2>&1 &
/sandbox/helpdesk/mcp-venv/bin/python fake_mcp.py 8765 </dev/null >/tmp/fake_mcp.log 2>&1 &
if [ "${HELPDESK_GATEWAY:-ogx}" = praxis ]; then
    # Fill in the model server's host; with guardrails off, drop the guardrail filter.
    host=$(printf '%s' "$LITELLM_API_URL" | sed -E 's#^[a-z]+://([^/:]+).*#\1#')
    # Praxis AI reloads on any change in its config's directory, so keep the
    # config away from the logs in /tmp.
    mkdir -p /tmp/praxis-config
    sed "s/__MODEL_HOST__/$host/g" praxis/praxis.yaml >/tmp/praxis-config/praxis.yaml
    if [ "${HELPDESK_GUARDRAILS:-true}" != true ]; then
        sed -i '/# BEGIN guardrail/,/# END guardrail/d' /tmp/praxis-config/praxis.yaml
    fi
    praxis/praxis-ai -c /tmp/praxis-config/praxis.yaml </dev/null >/tmp/praxis.log 2>&1 &
else
    /sandbox/helpdesk/.venv/bin/ogx run --insecure config.yaml </dev/null >/tmp/ogx.log 2>&1 &
fi

wait_for() {
    for _ in $(seq 600); do
        if curl -s -o /dev/null "$1"; then return 0; fi
        sleep 0.2
    done
    echo "$2 did not start:" >&2
    tail -n 40 "$3" >&2
    exit 1
}
wait_for http://127.0.0.1:8765/mcp "The fake helpdesk MCP server" /tmp/fake_mcp.log
wait_for http://127.0.0.1:8322/docs "The guardrail adapter" /tmp/moderation.out
if [ "${HELPDESK_GATEWAY:-ogx}" = praxis ]; then
    wait_for http://127.0.0.1:8080/ "Praxis AI" /tmp/praxis.log
else
    wait_for http://127.0.0.1:8321/v1/health "OGX" /tmp/ogx.log
fi

exec "$@"
