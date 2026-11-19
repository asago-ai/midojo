"""The midojo suite: what to ask, what to inject, and the environment that answers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

CANARY = "MIDOJO-CANARY-7f3a"


@dataclass(frozen=True)
class UserTask:
    id: str
    prompt: str
    tool: str
    """The carrier the task rides on: an operation name or ``topic:<id>``."""
    utility: dict[str, Any]


@dataclass(frozen=True)
class InjectionTask:
    id: str
    goal: str
    asi: tuple[str, ...]
    security: dict[str, Any]


@dataclass
class Suite:
    name: str
    environment: dict[str, Any]
    user_tasks: list[UserTask]
    injection_tasks: list[InjectionTask]

    @property
    def digest(self) -> str:
        body = json.dumps(asdict(self), sort_keys=True, default=str).encode()
        return "sha256:" + hashlib.sha256(body).hexdigest()


def suite_to_json(suite: Suite) -> dict[str, Any]:
    return {
        "name": suite.name,
        "environment": suite.environment,
        "user_tasks": [asdict(t) for t in suite.user_tasks],
        "injection_tasks": [{**asdict(t), "asi": list(t.asi)} for t in suite.injection_tasks],
    }


def suite_from_json(raw: dict[str, Any], default_name: str = "suite") -> Suite:
    return Suite(
        name=raw.get("name", default_name),
        environment=raw.get("environment") or {},
        user_tasks=[UserTask(**t) for t in raw["user_tasks"]],
        injection_tasks=[InjectionTask(**{**t, "asi": tuple(t.get("asi") or ())}) for t in raw["injection_tasks"]],
    )
