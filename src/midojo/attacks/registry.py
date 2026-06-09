"""The attack library: catalog of attack techniques (vehicles).

``AttackLibrary`` is the generic catalog mechanism; ``DEFAULT_LIBRARY`` is the
instance every suite resolves against, populated from ``attacks.builtin``.

Suites reference a vehicle by id through a probe's ``attack_type``; wrapping
happens once at suite-load time in ``YAMLTaskSuite._parse_probes``, so probes
hold final, ready-to-substitute strings.
"""

from __future__ import annotations

from midojo.attacks.builtin import BUILTIN_TECHNIQUES
from midojo.attacks.records import AttackTechnique


class AttackLibrary:
    """In-memory catalog of attack techniques, keyed by id."""

    def __init__(self, techniques: list[AttackTechnique] | None = None) -> None:
        self._techniques: dict[str, AttackTechnique] = {}
        for technique in techniques or []:
            self.register(technique)

    def register(self, technique: AttackTechnique) -> None:
        if technique.id in self._techniques:
            raise ValueError(f"Attack technique '{technique.id}' is already registered")
        self._techniques[technique.id] = technique

    def get(self, technique_id: str) -> AttackTechnique:
        if technique_id not in self._techniques:
            raise ValueError(f"Unsupported attack_type '{technique_id}'. Supported: {sorted(self._techniques)}")
        return self._techniques[technique_id]

    def ids(self) -> list[str]:
        return sorted(self._techniques)

    def wrap_payload(self, payload: str, technique_id: str) -> str:
        """Apply the named vehicle to a payload."""
        return self.get(technique_id).wrapper(payload)


# The default library every suite resolves against.
DEFAULT_LIBRARY = AttackLibrary(BUILTIN_TECHNIQUES)


def wrap_payload(payload: str, attack_type: str) -> str:
    """Apply the named attack_type vehicle from the default library."""
    return DEFAULT_LIBRARY.wrap_payload(payload, attack_type)
