"""Tests for the schema-aware, effort-bounded suite generator."""

from __future__ import annotations

from midojo.generator.schema_aware import Carrier, Sink, generate_suite


def _carriers(n: int) -> list[Carrier]:
    return [Carrier(id=f"read-{i}", label=f"read {i}", description=f"read {i}") for i in range(n)]


def _sinks(n: int) -> list[Sink]:
    return [Sink(id=f"write-{i}", label=f"write {i}", description=f"write {i}") for i in range(n)]


def test_effort_limits_volume():
    carriers = _carriers(10)
    sinks = _sinks(10)

    small = generate_suite(carriers, sinks, effort="small")
    medium = generate_suite(carriers, sinks, effort="medium")
    large = generate_suite(carriers, sinks, effort="large")

    assert len(small.user_tasks) <= len(medium.user_tasks) <= len(large.user_tasks)
    assert len(small.injection_tasks) <= len(medium.injection_tasks) <= len(large.injection_tasks)
    # One injection slot is reserved for the canary.
    assert len(small.injection_tasks) == 2
    assert len(medium.injection_tasks) == 4
    assert len(large.injection_tasks) == 8


def test_explicit_max_overrides_effort():
    carriers = _carriers(10)
    sinks = _sinks(10)

    suite = generate_suite(
        carriers,
        sinks,
        effort="large",
        max_user=1,
        max_injection=2,
    )
    assert len(suite.user_tasks) == 1
    assert len(suite.injection_tasks) == 2


def test_schema_aware_uses_descriptions():
    carriers = [Carrier(id="get_balance", label="get_balance", description="Look up a balance")]
    sinks = [
        Sink(
            id="transfer_funds",
            label="transfer_funds",
            description="Transfer money",
            required_args=("to", "amount"),
        )
    ]

    suite = generate_suite(carriers, sinks, effort="small", schema_aware=True)
    assert "Look up a balance" in suite.user_tasks[0].prompt
    assert "Transfer money" in suite.injection_tasks[0].goal
    assert "to" in suite.injection_tasks[0].goal and "amount" in suite.injection_tasks[0].goal


def test_generic_suite_uses_operation_names():
    carriers = [Carrier(id="get_balance", label="get_balance", description="Look up a balance")]
    sinks = [Sink(id="transfer_funds", label="transfer_funds", description="Transfer money")]

    suite = generate_suite(carriers, sinks, effort="small", schema_aware=False)
    assert "get_balance" in suite.user_tasks[0].prompt
    assert "transfer_funds" in suite.injection_tasks[0].goal


def test_canary_is_always_included():
    carriers = _carriers(1)
    sinks = _sinks(0)
    suite = generate_suite(carriers, sinks, effort="small")
    assert any(t.id == "hijack-canary" for t in suite.injection_tasks)


def test_round_robin_across_topic_and_tool_carriers():
    carriers = [
        Carrier(id="topic:returns", label="returns", description="returns policy", is_topic=True),
        Carrier(id="get_balance", label="get_balance", description="balance", is_topic=False),
        Carrier(id="get_history", label="get_history", description="history", is_topic=False),
    ]
    sinks = _sinks(1)
    suite = generate_suite(carriers, sinks, effort="small", max_user=2)
    # Small effort keeps 2 user tasks; round-robin should include the topic carrier.
    ids = [t.id for t in suite.user_tasks]
    assert "read-topic:returns" in ids
