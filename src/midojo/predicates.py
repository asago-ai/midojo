"""Declarative predicate evaluator for suite grading.

Predicates are parsed from YAML and cover common grading patterns: substring
checks, field equality, list matching, and boolean combinators. Suites whose
grading logic fits these patterns need no Python code.

Limitation: there is no "run arbitrary code" predicate. If a suite needs
custom logic (e.g. regex matching, numeric ranges, fuzzy comparison), a new
predicate type must be added here. A future `custom_function` predicate could
allow suites to reference a Python callable for cases the built-in set can't
express.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from midojo.types import Environment


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

    def evaluate(self, agent_output: str, pre_env: Environment, post_env: Environment) -> bool:
        return self.value.lower() in agent_output.lower()


@dataclass
class OutputContainsAll:
    values: list[str]

    def evaluate(self, agent_output: str, pre_env: Environment, post_env: Environment) -> bool:
        lower = agent_output.lower()
        return all(v.lower() in lower for v in self.values)


@dataclass
class OutputContainsAny:
    values: list[str]

    def evaluate(self, agent_output: str, pre_env: Environment, post_env: Environment) -> bool:
        lower = agent_output.lower()
        return any(v.lower() in lower for v in self.values)


@dataclass
class EnvFieldEquals:
    field: str
    value: Any

    def evaluate(self, agent_output: str, pre_env: Environment, post_env: Environment) -> bool:
        return resolve_field(post_env, self.field) == self.value


@dataclass
class EnvFieldContains:
    field: str
    value: str

    def evaluate(self, agent_output: str, pre_env: Environment, post_env: Environment) -> bool:
        field_val = resolve_field(post_env, self.field)
        return self.value.lower() in str(field_val).lower()


@dataclass
class EnvListAnyMatch:
    field: str
    match: dict[str, str]

    def evaluate(self, agent_output: str, pre_env: Environment, post_env: Environment) -> bool:
        items = resolve_field(post_env, self.field)
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

    def evaluate(self, agent_output: str, pre_env: Environment, post_env: Environment) -> bool:
        items = resolve_field(post_env, self.field)
        return isinstance(items, list) and len(items) == self.count


@dataclass
class EnvFieldUnchanged:
    field: str

    def evaluate(self, agent_output: str, pre_env: Environment, post_env: Environment) -> bool:
        return resolve_field(pre_env, self.field) == resolve_field(post_env, self.field)


@dataclass
class AllOf:
    predicates: list[Predicate]

    def evaluate(self, agent_output: str, pre_env: Environment, post_env: Environment) -> bool:
        return all(p.evaluate(agent_output, pre_env, post_env) for p in self.predicates)


@dataclass
class AnyOf:
    predicates: list[Predicate]

    def evaluate(self, agent_output: str, pre_env: Environment, post_env: Environment) -> bool:
        return any(p.evaluate(agent_output, pre_env, post_env) for p in self.predicates)


@dataclass
class Not:
    predicate: Predicate

    def evaluate(self, agent_output: str, pre_env: Environment, post_env: Environment) -> bool:
        return not self.predicate.evaluate(agent_output, pre_env, post_env)


Predicate = (
    OutputContains
    | OutputContainsAll
    | OutputContainsAny
    | EnvFieldEquals
    | EnvFieldContains
    | EnvListAnyMatch
    | EnvListCount
    | EnvFieldUnchanged
    | AllOf
    | AnyOf
    | Not
)

# ---------------------------------------------------------------------------
# Parser: raw YAML dict -> Predicate
# ---------------------------------------------------------------------------

_PARSERS: dict[str, type] = {
    "output_contains": OutputContains,
    "output_contains_all": OutputContainsAll,
    "output_contains_any": OutputContainsAny,
    "env_field_equals": EnvFieldEquals,
    "env_field_contains": EnvFieldContains,
    "env_list_any_match": EnvListAnyMatch,
    "env_list_count": EnvListCount,
    "env_field_unchanged": EnvFieldUnchanged,
    "all_of": AllOf,
    "any_of": AnyOf,
    "not": Not,
}


PREDICATE_TYPES: frozenset[str] = frozenset(_PARSERS)


def parse_predicate(raw: dict) -> Predicate:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise ValueError(f"Predicate must be a dict with exactly one key, got: {raw!r}")

    key = next(iter(raw))
    value = raw[key]

    if key not in _PARSERS:
        raise ValueError(f"Unknown predicate type: {key!r}. Must be one of: {sorted(_PARSERS)}")

    if key == "output_contains":
        return OutputContains(value=value)
    elif key == "output_contains_all":
        return OutputContainsAll(values=value)
    elif key == "output_contains_any":
        return OutputContainsAny(values=value)
    elif key == "env_field_equals":
        return EnvFieldEquals(field=value["field"], value=value["value"])
    elif key == "env_field_contains":
        return EnvFieldContains(field=value["field"], value=value["value"])
    elif key == "env_list_any_match":
        return EnvListAnyMatch(field=value["field"], match=value["match"])
    elif key == "env_list_count":
        return EnvListCount(field=value["field"], count=value["count"])
    elif key == "env_field_unchanged":
        return EnvFieldUnchanged(field=value["field"] if isinstance(value, dict) else value)
    elif key == "all_of":
        return AllOf(predicates=[parse_predicate(p) for p in value])
    elif key == "any_of":
        return AnyOf(predicates=[parse_predicate(p) for p in value])
    elif key == "not":
        return Not(predicate=parse_predicate(value))

    raise ValueError(f"Unhandled predicate type: {key!r}")


def evaluate_predicate(
    predicate: Predicate, agent_output: str, pre_env: Environment, post_env: Environment
) -> bool:
    return predicate.evaluate(agent_output, pre_env, post_env)
