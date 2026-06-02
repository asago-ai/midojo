"""Probe placeholder substitution.

Suite YAML embeds probe placeholders like ``{injection_task_0:main}`` in
environment fields and user-task prompts. At evaluation time the active
injections map (``"<task_id>:<probe_id>" -> payload``) is substituted in;
placeholders with no active probe collapse to the empty string.

Shared by the environment backend (which templates the env state) and the
suite (which templates user-task prompts).
"""

from __future__ import annotations

import re

PROBE_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_]\w*):([A-Za-z_]\w*)\}")


def substitute_probes(text: str, injections: dict[str, str]) -> str:
    return PROBE_PLACEHOLDER_RE.sub(
        lambda m: injections.get(f"{m.group(1)}:{m.group(2)}", ""),
        text,
    )
