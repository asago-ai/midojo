"""Applying injection instructions to a tool's result.

An interception adapter (the MCP SDK, a Claude Code hook, a PI extension) reads
the evaluation's injection plan and, for each tool call, splices any matching
``tool_output`` payload into the result the agent is about to see. This module
is that splice: pure, synchronous, no I/O, no network. The adapters own the
transport; this owns the string manipulation, so the behaviour is identical
across them and testable without a control plane.

Matching is deliberately *not* first-match-wins. Every instruction whose target
selects this tool applies, in plan order -- a wildcard (``target.tool is None``)
never shadows a later tool-specific instruction, and two instructions for the
same tool both land.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from midojo.channels import Channel, InjectionMode
from midojo.types import InjectionInstruction

logger = logging.getLogger("midojo.injection")

# Field an adapter falls back to when a payload cannot be embedded into existing
# text -- a structured tool result gains this key rather than losing its shape.
ANNOTATION_FIELD = "_annotation"


def matching_output_instructions(plan: list[InjectionInstruction], tool_name: str) -> list[InjectionInstruction]:
    """Every ``tool_output`` instruction that selects ``tool_name``, in order.

    A ``target.tool`` of ``None`` matches any tool; otherwise it matches by
    exact name. All matches are returned -- the caller applies them in order.
    """
    return [
        i for i in plan if i.channel == Channel.TOOL_OUTPUT and (i.target.tool is None or i.target.tool == tool_name)
    ]


def apply_output_instructions(result: str, plan: list[InjectionInstruction], tool_name: str) -> str:
    """Apply every matching ``tool_output`` instruction to ``result``, in order."""
    for instruction in matching_output_instructions(plan, tool_name):
        result = execute_injection(result, instruction)
    return result


def execute_injection(result: str, instruction: InjectionInstruction) -> str:
    """Splice one instruction's payload into ``result`` per its mode.

    - ``replace``   -- discard the real result, return the payload alone.
    - ``append``    -- the payload on a new line after the real result.
    - ``new_field`` -- add the payload as an annotation field on a JSON object;
      falls back to ``append`` when the result is not a JSON object.
    - ``embed``     -- splice the payload into an existing text field (the named
      one, else an auto-detected one), preserving the rest of the structure;
      falls back to an annotation field, then to ``append``.
    """
    payload = instruction.payload
    mode = instruction.mode

    if mode == InjectionMode.REPLACE:
        return payload
    if mode == InjectionMode.APPEND:
        return _append(result, payload)
    if mode == InjectionMode.NEW_FIELD:
        return _annotate(result, payload) or _append(result, payload)

    # embed
    target_field = instruction.target.field
    if target_field is not None:
        spliced = _splice_into_field(result, target_field, payload)
        if spliced is not None:
            return spliced
    best = _find_best_field(result)
    if best is not None:
        spliced = _splice_into_field(result, best, payload)
        if spliced is not None:
            return spliced
    return _annotate(result, payload) or _append(result, payload)


def _append(result: str, payload: str) -> str:
    return f"{result}\n{payload}" if result else payload


def _annotate(result: str, payload: str) -> str | None:
    """Add ``payload`` as an annotation field on a JSON object, or ``None``."""
    data = _load_json(result)
    if isinstance(data, dict):
        data[ANNOTATION_FIELD] = payload
        return json.dumps(data)
    return None


def _splice_into_field(result: str, field: str, payload: str) -> str | None:
    """Append the payload to a string field, top level or one list level deep.

    Returns the re-serialised JSON, or ``None`` if the field is absent or is not
    a string (a numeric or boolean field is never stringified -- that corrupts
    the value and is the kind of silent mangling this guard exists to prevent).
    """
    data = _load_json(result)
    if not isinstance(data, dict):
        return None
    if field in data and isinstance(data[field], str):
        data[field] = _join(data[field], payload)
        return json.dumps(data)
    for value in data.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and field in item and isinstance(item[field], str):
                    item[field] = _join(item[field], payload)
                    return json.dumps(data)
    return None


def _find_best_field(result: str) -> str | None:
    """Name of the longest multi-word string field -- the most natural carrier."""
    data = _load_json(result)
    if data is None:
        return None
    best_name: str | None = None
    best_len = -1
    for name, value in _string_fields(data):
        if " " in value and len(value) > best_len:
            best_name, best_len = name, len(value)
    return best_name


def _string_fields(data: Any, depth: int = 0) -> list[tuple[str, str]]:
    """(name, value) for string fields, top level and one list level deep."""
    if depth > 1:
        return []
    out: list[tuple[str, str]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                out.append((key, value))
            elif isinstance(value, list):
                for item in value:
                    out.extend(_string_fields(item, depth + 1))
    elif isinstance(data, list):
        for item in data:
            out.extend(_string_fields(item, depth + 1))
    return out


def _join(existing: str, payload: str) -> str:
    return f"{existing} {payload}" if existing else payload


def _load_json(result: str) -> Any:
    try:
        return json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return None
