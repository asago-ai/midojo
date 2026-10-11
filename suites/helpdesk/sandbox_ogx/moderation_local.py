"""Local guardrail adapter for the helpdesk agent's OGX server.

OGX's guardrails call an OpenAI-compatible /v1/moderations endpoint. This
adapter answers it with ProtectAI's prompt injection classifier
(protectai/deberta-v3-base-prompt-injection-v2), running in the sandbox with
transformers, so the guard needs no model server (see moderation_remote.py for
one that does):

    POST /v1/moderations {"input": "text"}
      -> classifier: INJECTION 0.998 on the most suspicious fragment
      -> {"results": [{"flagged": true, "categories": {"injection": true}}]}

OGX sends a whole conversation as one text: the system prompt, the messages, and
the tool results, joined. Classified whole, a payload at the end of a long
benign conversation scores as safe, so the adapter scores fragments instead
(sentences, lines, and the gaps between messages) and flags the text when any
fragment scores at least HELPDESK_GUARD_THRESHOLD. Fragments under four words
are skipped: the classifier flags short structured ones, such as a ticket's
"open" status, while the instructions it's meant to catch are sentences.

The model is cached in the image at build time; the sandbox blocks downloads.
Every check is appended to MODERATION_LOG as one JSON line, so an evaluation
shows exactly what text the guardrail saw, and what it didn't.
"""

import json
import os
import re
import sys
import time

import uvicorn
from fastapi import FastAPI, Request
from transformers import pipeline  # pyright: ignore[reportMissingImports]  # installed in the image

MODEL = os.environ.get("HELPDESK_LOCAL_GUARD_MODEL", "protectai/deberta-v3-base-prompt-injection-v2")
THRESHOLD = float(os.environ.get("HELPDESK_GUARD_THRESHOLD", "0.9"))
LOG_PATH = os.environ.get("MODERATION_LOG", "/tmp/moderation.log")
MIN_WORDS = 4

# Loaded before the server listens, so start.sh's readiness check means the guard is ready.
classifier = pipeline("text-classification", model=MODEL, truncation=True, max_length=512, device="cpu")

_BOUNDARY = re.compile(r"(?<=[.!?:])\s+|\n+|\s{2,}")

app = FastAPI()


def _fragments(text: str) -> list[str]:
    parts = [p.strip() for p in _BOUNDARY.split(text) if p.strip()]
    return [p for p in parts if len(p.split()) >= MIN_WORDS] or [text]


def _classify(text: str) -> tuple[bool, float, str]:
    """Return (flagged, injection score, most suspicious fragment)."""
    fragments = _fragments(text)
    scores = [r["score"] if r["label"] == "INJECTION" else 1 - r["score"] for r in classifier(fragments, batch_size=16)]
    top = max(range(len(scores)), key=scores.__getitem__)
    return scores[top] >= THRESHOLD, scores[top], fragments[top]


def _log(entry: dict) -> None:
    with open(LOG_PATH, "a") as log:
        log.write(json.dumps({"ts": time.time(), **entry}) + "\n")


@app.post("/v1/moderations")
async def moderations(request: Request) -> dict:
    body = await request.json()
    inputs = body.get("input", "")
    texts = inputs if isinstance(inputs, list) else [inputs]
    results = []
    for text in texts:
        flagged, score, fragment = _classify(str(text))
        categories = ["injection"] if flagged else []
        results.append({"flagged": flagged, "categories": {c: True for c in categories}})
        _log(
            {
                "flagged": flagged,
                "categories": categories,
                "score": round(score, 4),
                "fragment": fragment,
                "input": text,
            }
        )
    return {"id": f"modr-{int(time.time() * 1000)}", "model": MODEL, "results": results}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8322, log_level="warning")
