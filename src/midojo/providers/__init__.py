"""Verification provider discovery and bootstrap."""

from __future__ import annotations

from midojo.verification import VerificationProvider

from .builtin import BuiltinPredicateProvider
from .rhacs import RhacsProvider

_KNOWN_PROVIDERS: list[type[VerificationProvider]] = [BuiltinPredicateProvider, RhacsProvider]


def discover_providers() -> dict[str, VerificationProvider]:
    """Instantiate providers that are configured via environment variables, keyed by name."""
    providers: dict[str, VerificationProvider] = {}
    for cls in _KNOWN_PROVIDERS:
        instance = cls.from_env()
        if instance is not None:
            providers[instance.name] = instance
    return providers


def bootstrap_providers() -> dict[str, VerificationProvider]:
    """Register predicate parsers from all known providers, then discover configured instances.

    Call this before loading any suite so that provider-contributed
    predicate types are available to parse_predicate().
    """
    from midojo.predicates import register_predicate_parser

    for cls in _KNOWN_PROVIDERS:
        for key, parser in cls.predicate_parsers().items():
            register_predicate_parser(key, parser)
    return discover_providers()
