"""Predicate registry and combinators.

This module is the dispatch layer for suite grading predicates. Concrete
predicate types are contributed by verification providers at startup via
register_predicate_parser(). The combinators (AllOf, AnyOf, Not) live
here because they compose predicates rather than belonging to any provider.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from midojo.types import Environment

GradingContext = dict[str, Any] | None


# ---------------------------------------------------------------------------
# Combinators
# ---------------------------------------------------------------------------


@dataclass
class AllOf:
    predicates: list[Any]

    def evaluate(
        self, agent_output: str, pre_env: Environment, post_env: Environment, ctx: GradingContext = None
    ) -> bool:
        return all(p.evaluate(agent_output, pre_env, post_env, ctx) for p in self.predicates)


@dataclass
class AnyOf:
    predicates: list[Any]

    def evaluate(
        self, agent_output: str, pre_env: Environment, post_env: Environment, ctx: GradingContext = None
    ) -> bool:
        return any(p.evaluate(agent_output, pre_env, post_env, ctx) for p in self.predicates)


@dataclass
class Not:
    predicate: Any

    def evaluate(
        self, agent_output: str, pre_env: Environment, post_env: Environment, ctx: GradingContext = None
    ) -> bool:
        return not self.predicate.evaluate(agent_output, pre_env, post_env, ctx)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_PARSERS: dict[str, Callable[[Any], Any]] = {
    "all_of": lambda v: AllOf(predicates=[parse_predicate(p) for p in v]),
    "any_of": lambda v: AnyOf(predicates=[parse_predicate(p) for p in v]),
    "not": lambda v: Not(predicate=parse_predicate(v)),
}


def register_predicate_parser(key: str, parser: Callable[[Any], Any]) -> None:
    """Register a predicate parser contributed by a verification provider."""
    _PARSERS[key] = parser


def parse_predicate(raw: dict) -> Any:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise ValueError(f"Predicate must be a dict with exactly one key, got: {raw!r}")

    key = next(iter(raw))
    value = raw[key]

    if key not in _PARSERS:
        raise ValueError(f"Unknown predicate type: {key!r}. Must be one of: {sorted(_PARSERS)}")

    return _PARSERS[key](value)


def evaluate_predicate(
    predicate: Any,
    agent_output: str,
    pre_env: Environment,
    post_env: Environment,
    ctx: GradingContext = None,
) -> bool:
    return predicate.evaluate(agent_output, pre_env, post_env, ctx)
