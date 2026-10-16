"""Tests for attackers and the attempt loop's metrics and result cells."""

from __future__ import annotations

import pytest

from midojo.attacks import AttackAttempt, AttemptOutcome, StaticAttacker
from midojo.orchestrator import _attempt_metrics, _security_cell, _utility_cell


def _outcome(attempt: int, *, delivered: bool = True, broke: bool = False, utility: bool = True) -> AttemptOutcome:
    return AttemptOutcome(
        attempt=attempt,
        injections={"t:p": "payload"},
        delivered=delivered,
        delivered_where=["Read"] if delivered else [],
        broke=broke,
        security_reason="output_contains" if broke else None,
        utility=utility,
        agent_output="...",
        eval_id=f"eval{attempt}",
    )


class TestStaticAttacker:
    @pytest.mark.asyncio
    async def test_returns_the_configured_injections(self) -> None:
        attempt = await StaticAttacker({"t:p": "payload"}).propose(None, [])
        assert isinstance(attempt, AttackAttempt)
        assert attempt.injections == {"t:p": "payload"}

    @pytest.mark.asyncio
    async def test_ignores_goal_and_history(self) -> None:
        attacker = StaticAttacker({"t:p": "payload"})
        first = await attacker.propose(None, [])
        second = await attacker.propose("anything", [_outcome(1)])
        assert first.injections == second.injections == {"t:p": "payload"}

    @pytest.mark.asyncio
    async def test_hands_out_independent_copies(self) -> None:
        attacker = StaticAttacker({"t:p": "payload"})
        attempt = await attacker.propose(None, [])
        attempt.injections["t:p"] = "mutated"
        assert (await attacker.propose(None, [])).injections == {"t:p": "payload"}


class TestAttemptMetrics:
    def test_records_the_first_breaking_attempt(self) -> None:
        m = _attempt_metrics([_outcome(1), _outcome(2, broke=True), _outcome(3, broke=True)])
        assert m == {"attempts_run": 3, "attempts_to_break": 2, "delivered": 3, "successes": 2}

    def test_never_breaks(self) -> None:
        m = _attempt_metrics([_outcome(k) for k in range(1, 4)])
        assert m["attempts_to_break"] is None
        assert m["successes"] == 0

    def test_delivered_counts_only_delivered_attempts(self) -> None:
        m = _attempt_metrics([_outcome(1, delivered=False), _outcome(2, broke=True)])
        assert m["delivered"] == 1


class TestResultCells:
    def test_single_attempt_has_no_tally(self) -> None:
        # The default run renders exactly as before.
        outcomes = [_outcome(1, broke=True)]
        assert _security_cell(True, outcomes, attempts=1).plain == "💀 attack succeeded"
        assert _utility_cell(True, outcomes, attempts=1).plain == "✅ task completed"

    def test_security_tallies_breaking_attempts(self) -> None:
        outcomes = [_outcome(1), _outcome(2, broke=True), _outcome(3)]
        assert _security_cell(True, outcomes, attempts=3).plain == "💀 attack succeeded  (1/3)"

    def test_security_tallies_a_resisted_pair(self) -> None:
        outcomes = [_outcome(k) for k in range(1, 4)]
        assert _security_cell(False, outcomes, attempts=3).plain == "🛡️ attack failed  (0/3)"

    def test_na_security_stays_plain(self) -> None:
        outcomes = [_outcome(k, delivered=False) for k in range(1, 4)]
        assert _security_cell(None, outcomes, attempts=3).plain == "N/A"

    def test_utility_tallies_completed_attempts(self) -> None:
        outcomes = [_outcome(1), _outcome(2, utility=False), _outcome(3)]
        assert _utility_cell(True, outcomes, attempts=3).plain == "✅ task completed  (2/3)"
