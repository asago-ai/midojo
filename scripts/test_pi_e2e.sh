#!/usr/bin/env bash
set -euo pipefail

set -a
source .env
set +a

PORT=8099
BASE_URL="http://localhost:${PORT}"
PI_AGENT_DIR="src/midojo/suites/weather/pi_agent"

echo "=== Generating Pi agent config from env ==="
cat > "${PI_AGENT_DIR}/.pi/models.json" <<MODELS
{
  "providers": {
    "litellm": {
      "baseUrl": "${LITELLM_API_URL}",
      "api": "openai-completions",
      "models": [{"id": "${LITELLM_MODEL}"}]
    }
  }
}
MODELS

cat > "${PI_AGENT_DIR}/.pi/auth.json" <<AUTH
{
  "litellm": {"type": "api_key", "key": "LITELLM_API_KEY"}
}
AUTH

cleanup() {
    if [[ -n "${SERVER_PID:-}" ]]; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "=== Starting midojo server on port ${PORT} ==="
uv run midojo-serve --port "$PORT" --real-mcp-url "http://localhost:9999" &
SERVER_PID=$!

echo "Waiting for server..."
for i in $(seq 1 20); do
    if curl -sf "${BASE_URL}/suite" >/dev/null 2>&1; then
        echo "Server ready"
        break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "FAIL: Server process died"
        exit 1
    fi
    sleep 0.5
done

if ! curl -sf "${BASE_URL}/suite" >/dev/null 2>&1; then
    echo "FAIL: Server failed to start after 10s"
    exit 1
fi

echo "=== Creating run ==="
RUN_ID=$(curl -sf -X POST "${BASE_URL}/runs" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Run ID: ${RUN_ID}"

echo "=== Creating evaluation ==="
EVAL_RESP=$(curl -sf -X POST "${BASE_URL}/runs/${RUN_ID}/evaluations" \
    -H "Content-Type: application/json" \
    -d '{"user_task_id": "user_task_0"}')
EVAL_ID=$(echo "$EVAL_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
PROMPT=$(echo "$EVAL_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['prompt'])")
echo "Eval ID: ${EVAL_ID}"
echo "Prompt: ${PROMPT}"

echo "=== Checking initial environment ==="
curl -sf "${BASE_URL}/runs/${RUN_ID}/evaluations/${EVAL_ID}/environment" | python3 -m json.tool

echo ""
echo "=== Invoking Pi agent (--print) ==="
(
    cd "$PI_AGENT_DIR"
    MIDOJO_URL="$BASE_URL" MIDOJO_RUN_ID="$RUN_ID" MIDOJO_EVAL_ID="$EVAL_ID" \
        npx @mariozechner/pi-coding-agent \
        --print \
        --no-session \
        "$PROMPT" \
        2>&1
) | tee /tmp/pi_agent_output.txt

echo ""
echo "=== Checking function calls recorded ==="
FC_RESP=$(curl -sf "${BASE_URL}/runs/${RUN_ID}/evaluations/${EVAL_ID}/function-calls")
echo "$FC_RESP" | python3 -m json.tool

FC_COUNT=$(echo "$FC_RESP" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
echo ""
if [[ "$FC_COUNT" -gt 0 ]]; then
    echo "PASS: ${FC_COUNT} function call(s) recorded"
else
    echo "FAIL: No function calls recorded"
    exit 1
fi

echo ""
echo "=== Checking environment after agent run ==="
curl -sf "${BASE_URL}/runs/${RUN_ID}/evaluations/${EVAL_ID}/environment" | python3 -m json.tool

echo ""
echo "=== Done ==="
