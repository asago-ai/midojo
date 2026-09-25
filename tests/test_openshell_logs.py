"""Tests for OCSF shorthand parsing against lines captured from an OpenShell 0.1.0 gateway."""

from __future__ import annotations

from midojo.backends.openshell.logs import parse_ocsf_lines

# Verbatim OCSF messages from a live 0.1.0-pre.12 gateway (Podman driver): an
# allowed HTTP call, a denied hostname, and a denied literal IP, all from bash.
CAPTURED = [
    "CONFIG:READY [INFO] Policy DNS connected to isolation boundary",
    "NET:LISTEN [INFO] 127.0.0.1:3128",
    "NET:OPEN [INFO] host.containers.internal:17670",
    "SSH:OPEN [INFO] ALLOWED",
    "CONFIG:PUBLISHED [INFO] Policy DNS mapped example.com resolved=104.20.23.154,172.66.147.243 "
    "synthetic=198.18.0.2 ports=80 mapping_id=9e28b10b-6a8b-4bce-97c0-96ac036434a7",
    "NET:OPEN [INFO] ALLOWED /usr/bin/bash(0) -> example.com:80 [policy:web engine:opa]",
    "HTTP:GET [INFO] ALLOWED GET http://example.com/",
    "NET:REFUSE [MED] DENIED audit.ext-log.com [reason:policy_dns_ineligible]",
    "NET:OPEN [MED] DENIED /usr/bin/bash(0) -> audit.ext-log.com:443 [reason:transparent_tcp_policy_denied]",
    "NET:OPEN [MED] DENIED /usr/bin/bash(0) -> 1.1.1.1:443 [reason:transparent_tcp_policy_denied]",
]


def test_allowed_connection_keeps_caller_and_endpoint():
    events = parse_ocsf_lines(CAPTURED)
    assert events.network_allowed_endpoints == ["example.com:80"]
    assert events.network_allowed[0].binary == "/usr/bin/bash"


def test_dns_refusal_is_a_blocked_attempt_without_port():
    events = parse_ocsf_lines(CAPTURED)
    refusal = events.network_blocked[0]
    assert refusal.endpoint == "audit.ext-log.com"
    assert refusal.port is None
    assert refusal.binary is None


def test_denied_connections_are_recorded():
    events = parse_ocsf_lines(CAPTURED)
    assert events.network_blocked_endpoints == ["audit.ext-log.com", "audit.ext-log.com:443", "1.1.1.1:443"]


def test_http_event_without_caller_is_parsed():
    events = parse_ocsf_lines(CAPTURED)
    assert [(e.method, e.url) for e in events.http_allowed] == [("GET", "http://example.com/")]


def test_events_without_a_decision_are_ignored():
    events = parse_ocsf_lines(["NET:LISTEN [INFO] 127.0.0.1:3128", "NET:OPEN [INFO] host.containers.internal:17670"])
    assert not events.network_allowed
    assert not events.network_blocked


def test_network_callers_are_distinct_executables():
    events = parse_ocsf_lines(CAPTURED)
    assert events.network_callers == ["/usr/bin/bash"]
