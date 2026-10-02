#!/bin/sh
# Starts the fake alerts MCP server on localhost:8765, where the weather
# suite's .pi/mcp.json points PI, waits until it answers, then runs the agent
# command passed as arguments.
#
# The server logs to a file so it doesn't hold the agent's output open after
# the agent exits.
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
