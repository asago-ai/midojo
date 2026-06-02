"""Verification providers — the second of the engine's two observability axes.

A provider defines *how an outcome is checked*. Today there is one: declarative
predicates over the agent output and the env state snapshots
(:class:`PredicateProvider`). The protocol is the seam where richer providers
plug in later — filesystem inspection, network-traffic analysis, k8s API
auditing, Red Hat ACS / StackRox runtime checks (e.g. "did a new process
spawn?", "was there a network request to domain X?") — without the suite or
grading code needing to know which provider backs a given check.

How dispatch works: a ``utility:`` / ``security:`` block in ``suite.yaml`` is a
single-key dict. If that key names a registered provider, the provider parses
the value. Otherwise the block falls through to the predicate provider (which
owns ``output_contains``, ``env_field_equals``, ``all_of``, ...). This keeps
every existing suite working unchanged while leaving room for, say::

    security:
      acs:
        network_request: {domain: evil.com}

A provider sees the full :class:`VerificationContext`, not just the env — that
``observations`` bag is where backends will surface event streams that
providers like ACS consume (Phase 2+).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from midojo.predicates import PREDICATE_TYPES, Predicate, evaluate_predicate, parse_predicate
from midojo.types import Environment, FunctionCallRecord


@dataclass
class VerificationContext:
    """Everything a provider may inspect to decide pass/fail.

    ``observations`` is the extension point: backends keyed by name deposit
    event streams here (e.g. ``observations["acs"] = [ProcessEvent, ...]``) for
    providers to read. Predicate checks ignore it.
    """

    agent_output: str
    pre_environment: Environment
    post_environment: Environment
    function_calls: list[FunctionCallRecord] = field(default_factory=list)
    observations: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class VerificationProvider(Protocol):
    """Parses a check spec at load time and evaluates it at grade time."""

    name: str

    def parse(self, spec: Any) -> Any:
        """Validate/compile a raw check spec into a reusable check object."""
        ...

    def evaluate(self, check: Any, ctx: VerificationContext) -> bool:
        """Return whether ``check`` holds for ``ctx``."""
        ...


class PredicateProvider:
    """Default provider: declarative predicates over output + env snapshots.

    Its check object is a :class:`~midojo.predicates.Predicate`; it is the
    fallback for any check block whose key is not a registered provider.
    """

    name = "predicate"

    def parse(self, spec: dict) -> Predicate:
        return parse_predicate(spec)

    def evaluate(self, check: Predicate, ctx: VerificationContext) -> bool:
        return evaluate_predicate(check, ctx.agent_output, ctx.pre_environment, ctx.post_environment)


@dataclass
class Check:
    """A parsed check bound to the provider that evaluates it."""

    provider: VerificationProvider
    parsed: Any

    def evaluate(self, ctx: VerificationContext) -> bool:
        return self.provider.evaluate(self.parsed, ctx)


# --- Provider registry + dispatch ---

_PREDICATE_PROVIDER = PredicateProvider()
_PROVIDERS: dict[str, VerificationProvider] = {}


def register_provider(provider: VerificationProvider) -> None:
    """Register a named provider so suites can address it by its top-level key.

    Guards against a provider name shadowing a predicate type (which would make
    a check silently route to the wrong evaluator) or an already-registered
    provider.
    """
    if provider.name in PREDICATE_TYPES:
        raise ValueError(f"Provider name {provider.name!r} shadows a predicate type")
    if provider.name in _PROVIDERS:
        raise ValueError(f"Provider name {provider.name!r} is already registered")
    _PROVIDERS[provider.name] = provider


def parse_check(raw: dict) -> Check:
    """Resolve a ``utility:`` / ``security:`` block to a provider-bound check.

    A registered provider name as the single key dispatches to that provider;
    anything else falls through to predicates (preserving existing behavior and
    error messages for unknown predicate types).
    """
    if isinstance(raw, dict) and len(raw) == 1:
        key = next(iter(raw))
        provider = _PROVIDERS.get(key)
        if provider is not None:
            return Check(provider=provider, parsed=provider.parse(raw[key]))
    return Check(provider=_PREDICATE_PROVIDER, parsed=_PREDICATE_PROVIDER.parse(raw))
