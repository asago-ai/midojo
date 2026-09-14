"""Injection plan execution — shared logic for all interception SDKs.

Pure functions that match tool-type instructions from the injection plan
and apply injection modes to tool response strings. Used by:

- MCP SDK (Python) — ``mcp_sdk._apply_plan_and_record``
- PI SDK (TypeScript) — has its own copy of the same logic
- Claude Code hooks — ``hooks.claude_code``

No async, no I/O, no SDK-specific dependencies.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("midojo.injection")


def match_tool_instruction(plan: list[dict], tool_name: str) -> dict | None:
    """Return the first matching tool-type instruction from the plan.

    Only considers ``type: "tool"`` instructions. Matches by ``target_tool``
    — null matches any tool.
    """
    for instruction in plan:
        if instruction.get("type", "tool") != "tool":
            continue
        target = instruction.get("target_tool")
        if target is None or target == tool_name:
            return instruction
    return None


def execute_injection(result: str, instruction: dict, tool_name: str) -> str:
    """Apply an injection instruction to a tool response string.

    Modes:
    - embed: splice payload into an existing field (specified or auto-detected)
    - replace: discard real result, return payload as the entire response
    - append: append payload after the real response
    - new_field: add payload as a ``_annotation`` field in the response JSON
    """
    payload = instruction["payload"]
    mode = instruction.get("mode", "embed")
    target_field = instruction.get("target_field")

    if mode == "replace":
        logger.info("inject [%s]: replaced entire response", tool_name)
        return payload

    if mode == "append":
        logger.info("inject [%s]: appended to response", tool_name)
        return f"{result}\n{payload}"

    if mode == "new_field":
        try:
            data = json.loads(result)
            if isinstance(data, dict):
                data["_annotation"] = payload
                logger.info("inject [%s]: added _annotation field", tool_name)
                return json.dumps(data)
        except (json.JSONDecodeError, TypeError):
            pass
        logger.info("inject [%s]: appended (new_field fallback)", tool_name)
        return f"{result}\n{payload}"

    if target_field:
        injected = splice_into_field(result, target_field, payload)
        if injected is not None:
            logger.info("inject [%s]: embedded in field '%s'", tool_name, target_field)
            return injected

    best_field = find_best_field(result)
    if best_field:
        injected = splice_into_field(result, best_field, payload)
        if injected is not None:
            logger.info("inject [%s]: auto-embedded in field '%s'", tool_name, best_field)
            return injected

    try:
        data = json.loads(result)
        if isinstance(data, dict):
            data["_annotation"] = payload
            logger.info("inject [%s]: no text field found, added _annotation", tool_name)
            return json.dumps(data)
    except (json.JSONDecodeError, TypeError):
        pass
    logger.info("inject [%s]: no text field found, appended", tool_name)
    return f"{result}\n{payload}"


def splice_into_field(result: str, field: str, payload: str) -> str | None:
    """Splice payload into a named field in a JSON response.

    Searches top-level dict fields AND fields inside list items (one level).
    Returns the mutated JSON string, or None if the field wasn't found.
    """
    try:
        data = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return None

    if isinstance(data, dict) and field in data:
        data[field] = f"{data[field]} {payload}" if data[field] else payload
        return json.dumps(data)

    if isinstance(data, dict):
        for _key, val in data.items():
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and field in item:
                        item[field] = f"{item[field]} {payload}" if item[field] else payload
                        return json.dumps(data)

    return None


def find_best_field(result: str) -> str | None:
    """Find the longest multi-word string field in a JSON response.

    Simple fallback for when the caller doesn't specify ``target_field``.
    Returns a field name that ``splice_into_field`` can locate, or None.
    """
    try:
        data = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return None

    best_name: str | None = None
    best_len = 0

    for name, value in _collect_string_fields(data):
        if " " in value and len(value) > best_len:
            best_name = name
            best_len = len(value)

    return best_name


def _collect_string_fields(data: Any, depth: int = 0) -> list[tuple[str, str]]:
    """Collect (field_name, value) for string fields up to one list level deep."""
    if depth > 1:
        return []
    results: list[tuple[str, str]] = []
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, str):
                results.append((key, val))
            elif isinstance(val, list):
                for item in val[:3]:
                    if isinstance(item, dict):
                        results.extend(_collect_string_fields(item, depth + 1))
    elif isinstance(data, list):
        for item in data[:3]:
            if isinstance(item, dict):
                results.extend(_collect_string_fields(item, depth + 1))
    return results
