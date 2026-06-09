"""Catalog record shapes for the attack library.

The library will hold two kinds of entry (issue #36):

* **Vehicles** — *how* you attack: a `Callable[[str], str]` that wraps a payload
  (the cargo) in a delivery technique. ``AttackTechnique`` below.
* **Payload sets** — *what* you say: a corpus of payload strings (e.g. Garak's
  hijack strings) that a suite probe samples from. Not implemented yet.

OWASP ASI categorization (see ``attacks.taxonomy``) is a property of the *harm*
an attack probes for, so it lives on the injection task / payload (the cargo) —
not on the vehicle, which is a category-agnostic delivery mechanism.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# A vehicle: take a payload (cargo), return the wrapped payload.
PayloadWrapper = Callable[[str], str]


@dataclass(frozen=True)
class AttackTechnique:
    """A vehicle entry: a reusable wrapping technique plus its provenance.

    ``id`` is the name suites reference via a probe's ``attack_type``.
    ``source`` records provenance (e.g. ``"builtin"`` or
    ``"agentdojo:important_instructions"``) so imported attacks keep
    attribution.
    """

    id: str
    wrapper: PayloadWrapper
    description: str
    source: str = "builtin"
    references: tuple[str, ...] = ()
    license: str | None = None
