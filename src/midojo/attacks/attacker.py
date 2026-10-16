"""Attackers: the policy that picks each attempt's injection.

The rest of this package is the attack *material*: delivery techniques and
payload corpora. An attacker is the *policy* that uses it. For every attempt of
a (user task x injection task) pair it proposes the injection to deliver, and it
may learn from the outcomes of the attempts before. The orchestrator's attempt
loop is written against the :class:`Attacker` protocol, so a model-driven
attacker slots in beside :class:`StaticAttacker` without reshaping the loop.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AttackAttempt:
    """What an attacker proposes for one attempt.

    ``injections`` maps probe keys (``"<injection_task>:<probe>"``) to payload
    strings, the same mapping the orchestrator passes to ``create_evaluation``.
    """

    injections: dict[str, str]


@dataclass(frozen=True)
class AttemptOutcome:
    """The observed result of one attempt.

    Fed back to the attacker as history, and recorded in the run's results.
    ``delivered`` says the payload reached the agent at all; ``broke`` says the
    injection succeeded (the security check passed on a delivered payload).
    """

    attempt: int
    injections: dict[str, str]
    delivered: bool
    delivered_where: list[str]
    broke: bool
    security_reason: str | None
    utility: bool
    agent_output: str
    eval_id: str


class Attacker(Protocol):
    """Proposes the injection for each attempt, optionally adapting to history.

    ``propose`` is async so a model-driven attacker can call its own inference
    endpoint. ``goal`` is the objective for an attacker that pursues one; nothing
    supplies an objective yet, so the orchestrator passes ``None``. ``history``
    holds the outcomes of the pair's earlier attempts, in order.
    """

    async def propose(self, goal: str | None, history: Sequence[AttemptOutcome]) -> AttackAttempt: ...


class StaticAttacker:
    """Proposes the same suite-defined injection on every attempt.

    With one attempt this is MiDojo's original single-shot run. With K attempts
    it delivers the identical injection K times, each in a fresh sandbox, which
    shows how often it breaks the agent under the agent's own stochasticity. It
    ignores ``goal`` and ``history``: there is nothing to adapt.
    """

    def __init__(self, injections: dict[str, str]) -> None:
        self._injections = dict(injections)

    async def propose(self, goal: str | None, history: Sequence[AttemptOutcome]) -> AttackAttempt:
        return AttackAttempt(injections=dict(self._injections))
