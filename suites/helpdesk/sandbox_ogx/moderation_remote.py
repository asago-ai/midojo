"""Remote guardrail adapter for the helpdesk agent's OGX server.

OGX's guardrails call an OpenAI-compatible /v1/moderations endpoint. This
adapter answers it with a guard model served by the same OpenAI-compatible model
server as the agent's model (see moderation_local.py for a guard that runs in the
sandbox): Granite Guardian (default, "Yes"/"No" for its
default harm risk) or Llama Guard ("safe" / "unsafe\\nS10"):

    POST /v1/moderations {"input": "text"}
      -> guard model: "Yes" | "unsafe\\nS10"
      -> {"results": [{"flagged": true, "categories": {"harm": true}}]}

Every check is appended to MODERATION_LOG as one JSON line, so an evaluation
shows exactly what text the guardrail saw, and what it didn't.
"""

import asyncio
import json
import os
import sys
import time

import httpx
import uvicorn
from fastapi import FastAPI, Request

MODEL_SERVER = os.environ["LITELLM_API_URL"].rstrip("/")
API_KEY = os.environ.get("LITELLM_API_KEY", "none")
GUARD_MODEL = os.environ.get("HELPDESK_GUARD_MODEL", "granite-guardian-3-1-8b")
LOG_PATH = os.environ.get("MODERATION_LOG", "/tmp/moderation.log")

app = FastAPI()


RETRIES = 4


def _log(entry: dict) -> None:
    with open(LOG_PATH, "a") as log:
        log.write(json.dumps({"ts": time.time(), **entry}) + "\n")


async def _call_guard(client: httpx.AsyncClient, text: str) -> httpx.Response:
    """Call the guard model, retrying transient failures (rate limits, timeouts, 5xx)."""
    for attempt in range(RETRIES):
        try:
            resp = await client.post(
                f"{MODEL_SERVER}/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={
                    "model": GUARD_MODEL,
                    "messages": [{"role": "user", "content": text}],
                    "max_tokens": 20,
                    "temperature": 0,
                },
            )
            if resp.status_code != 429 and resp.status_code < 500:
                return resp
            error = f"HTTP {resp.status_code}: {resp.text[:300]}"
        except httpx.HTTPError as e:
            error = f"{type(e).__name__}: {e}"
        _log({"error": error, "attempt": attempt + 1})
        await asyncio.sleep(2**attempt)
    raise RuntimeError(f"guard model unavailable after {RETRIES} attempts: {error}")


async def _classify(client: httpx.AsyncClient, text: str) -> tuple[bool, list[str]]:
    resp = await _call_guard(client, text)
    if resp.is_error:
        _log({"error": f"HTTP {resp.status_code}: {resp.text[:300]}", "input": text})
    resp.raise_for_status()
    verdict = (resp.json()["choices"][0]["message"]["content"] or "").strip()
    words = verdict.split()
    first = words[0].lower() if words else ""
    if first == "yes":  # Granite Guardian: "Yes" means the text carries the risk (harm)
        return True, ["harm"]
    if first == "unsafe":  # Llama Guard: "unsafe" then the hazard categories
        return True, [c.strip(",") for c in words[1:]]
    return False, []


@app.post("/v1/moderations")
async def moderations(request: Request) -> dict:
    body = await request.json()
    inputs = body.get("input", "")
    texts = inputs if isinstance(inputs, list) else [inputs]
    results = []
    async with httpx.AsyncClient(timeout=60) as client:
        for text in texts:
            flagged, categories = await _classify(client, str(text))
            results.append({"flagged": flagged, "categories": {c: True for c in categories}})
            _log({"flagged": flagged, "categories": categories, "input": text})
    return {"id": f"modr-{int(time.time() * 1000)}", "model": GUARD_MODEL, "results": results}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8322, log_level="warning")
