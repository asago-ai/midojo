"""Built-in verification provider.

Checks agent output and in-memory environment state. These are the
predicates that ship with MiDojo — substring checks, field equality,
list matching, etc.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from midojo.predicates import EvaluationContext
from midojo.types import Environment
from midojo.verification import VerificationProvider


def resolve_field(env: Environment, path: str) -> Any:
    """Walk a dotted path into a Pydantic model."""
    current: Any = env
    for key in path.split("."):
        if isinstance(current, dict):
            current = current[key]
        else:
            current = getattr(current, key)
    return current


# ---------------------------------------------------------------------------
# Predicate types
# ---------------------------------------------------------------------------


@dataclass
class OutputContains:
    value: str

    def evaluate(self, ctx: EvaluationContext) -> bool:
        return self.value.lower() in ctx.agent_output.lower()


@dataclass
class OutputContainsAll:
    values: list[str]

    def evaluate(self, ctx: EvaluationContext) -> bool:
        lower = ctx.agent_output.lower()
        return all(v.lower() in lower for v in self.values)


@dataclass
class OutputContainsAny:
    values: list[str]

    def evaluate(self, ctx: EvaluationContext) -> bool:
        lower = ctx.agent_output.lower()
        return any(v.lower() in lower for v in self.values)


@dataclass
class EnvFieldEquals:
    field: str
    value: Any

    def evaluate(self, ctx: EvaluationContext) -> bool:
        return resolve_field(ctx.post_env, self.field) == self.value


@dataclass
class EnvFieldContains:
    field: str
    value: str

    def evaluate(self, ctx: EvaluationContext) -> bool:
        field_val = resolve_field(ctx.post_env, self.field)
        return self.value.lower() in str(field_val).lower()


@dataclass
class EnvListAnyMatch:
    field: str
    match: dict[str, str]

    def evaluate(self, ctx: EvaluationContext) -> bool:
        items = resolve_field(ctx.post_env, self.field)
        if not isinstance(items, list):
            return False
        for item in items:
            if isinstance(item, dict):
                if all(k in item and self.match[k].lower() in str(item[k]).lower() for k in self.match):
                    return True
            else:
                if all(
                    hasattr(item, k) and self.match[k].lower() in str(getattr(item, k)).lower() for k in self.match
                ):
                    return True
        return False


@dataclass
class EnvListCount:
    field: str
    count: int

    def evaluate(self, ctx: EvaluationContext) -> bool:
        items = resolve_field(ctx.post_env, self.field)
        return isinstance(items, list) and len(items) == self.count


@dataclass
class EnvFieldUnchanged:
    field: str

    def evaluate(self, ctx: EvaluationContext) -> bool:
        return resolve_field(ctx.pre_env, self.field) == resolve_field(ctx.post_env, self.field)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class BuiltinPredicateProvider(VerificationProvider):
    @property
    def name(self) -> str:
        return "builtin"

    @classmethod
    def predicate_parsers(cls) -> dict[str, Callable[[Any], Any]]:
        return {
            "output_contains": lambda v: OutputContains(value=v),
            "output_contains_all": lambda v: OutputContainsAll(values=v),
            "output_contains_any": lambda v: OutputContainsAny(values=v),
            "env_field_equals": lambda v: EnvFieldEquals(field=v["field"], value=v["value"]),
            "env_field_contains": lambda v: EnvFieldContains(field=v["field"], value=v["value"]),
            "env_list_any_match": lambda v: EnvListAnyMatch(field=v["field"], match=v["match"]),
            "env_list_count": lambda v: EnvListCount(field=v["field"], count=v["count"]),
            "env_field_unchanged": lambda v: EnvFieldUnchanged(field=v["field"] if isinstance(v, dict) else v),
        }

    def setup(self, created_at: str, completed_at: str) -> None:
        pass

    @classmethod
    def from_env(cls) -> BuiltinPredicateProvider:
        return cls()
