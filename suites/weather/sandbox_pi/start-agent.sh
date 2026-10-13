#!/bin/sh
# Starts the weather agent: points PI at the model, starts the fake alerts MCP
# server, then runs the agent command passed as arguments.
set -e

# 1. The model. The suite passes LITELLM_API_URL and LITELLM_MODEL into the
# sandbox at run time, like LITELLM_API_KEY, so one image works with any
# OpenAI-compatible model server. PI can't read them itself: it expands
# environment variables only in apiKey and headers, not in a provider's
# baseUrl or model IDs. Fill the @LITELLM_API_URL@ and @LITELLM_MODEL@
# placeholders in PI's config, JSON-escaped.
: "${LITELLM_API_URL:?LITELLM_API_URL is not set}"
: "${LITELLM_MODEL:?LITELLM_MODEL is not set}"
/sandbox/.venv/bin/python3 - /sandbox/.pi/agent/models.json /sandbox/.pi/agent/settings.json <<'PY'
import json
import os
import sys

for path in sys.argv[1:]:
    with open(path) as f:
        text = f.read()
    for name in ("LITELLM_API_URL", "LITELLM_MODEL"):
        text = text.replace(f"@{name}@", json.dumps(os.environ[name])[1:-1])
    with open(path, "w") as f:
        f.write(text)
PY

# 2. The fake alerts MCP server, on localhost:8765, where the weather suite's
# .pi/mcp.json points PI. Wait until it answers. It logs to a file so it
# doesn't hold the agent's output open after the agent exits.
/sandbox/.venv/bin/python3 /sandbox/midojo/fake_mcp.py 8765 </dev/null >/tmp/fake_mcp.log 2>&1 &
for _ in $(seq 100); do
    if curl -s -o /dev/null http://localhost:8765/mcp; then
        exec "$@"
    fi
    sleep 0.1
done
echo "The fake MCP server did not start:" >&2
cat /tmp/fake_mcp.log >&2
exit 1
