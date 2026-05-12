from __future__ import annotations

from typing import Any

from agentdojo.functions_runtime import TaskEnvironment
from pydantic import create_model


def _infer_type(value: Any, model_name: str) -> type:
    if isinstance(value, bool):
        return bool
    if isinstance(value, int):
        return int
    if isinstance(value, float):
        return float
    if isinstance(value, str):
        return str
    if isinstance(value, list):
        if not value:
            return list
        return list[_infer_type(value[0], f"{model_name}Item")]
    if isinstance(value, dict):
        return _make_model(model_name, value)
    return Any


def _fields_signature(d: dict) -> set[str]:
    return set(d.keys())


def _make_model(name: str, sample: dict) -> type:
    fields: dict[str, Any] = {}
    for key, value in sample.items():
        fields[key] = (_infer_type(value, f"{name}_{key.title().replace(' ', '')}"), ...)
    return create_model(name, **fields)


def _infer_field(key: str, value: Any, suite_name: str) -> tuple[type, Any]:
    """Return (type, default_or_ellipsis) for a top-level environment field."""
    if isinstance(value, list):
        if not value:
            return (list, [])
        item_type = _infer_type(value[0], f"{suite_name}_{key.title().replace(' ', '')}Item")
        return (list[item_type], ...)
    if isinstance(value, dict):
        vals = list(value.values())
        if vals and all(isinstance(v, dict) for v in vals):
            sigs = [_fields_signature(v) for v in vals]
            if len(set(map(frozenset, sigs))) == 1:
                nested = _make_model(
                    f"{suite_name}_{key.title().replace(' ', '')}Entry", vals[0]
                )
                return (dict[str, nested], ...)
        return (dict[str, Any], ...)
    return (_infer_type(value, f"{suite_name}_{key}"), ...)


def infer_environment_type(suite_name: str, env_data: dict) -> type[TaskEnvironment]:
    label = suite_name.title().replace(" ", "")
    fields: dict[str, Any] = {}
    for key, value in env_data.items():
        fields[key] = _infer_field(key, value, label)
    return create_model(f"{label}Environment", __base__=TaskEnvironment, **fields)
