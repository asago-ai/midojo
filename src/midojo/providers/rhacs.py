"""RHACS/StackRox verification provider.

Uses StackRox Central's REST API to check runtime events (process
executions, network flows) observed by the eBPF collector during
an evaluation.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from midojo.predicates import GradingContext
from midojo.types import Environment
from midojo.verification import VerificationProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# REST client for StackRox Central
# ---------------------------------------------------------------------------


class RoxClient:
    def __init__(self, endpoint: str, token: str, *, verify: bool = False) -> None:
        self._client = httpx.Client(
            base_url=f"https://{endpoint}/v1",
            headers={"Authorization": f"Bearer {token}"},
            verify=verify,
            timeout=30.0,
        )

    def resolve_deployment_id(self, namespace: str, deployment: str) -> str:
        query = f"Namespace:{namespace}+Deployment:{deployment}"
        resp = self._client.get("/deployments", params={"query": query})
        resp.raise_for_status()
        deployments = resp.json().get("deployments", [])
        if not deployments:
            raise ValueError(f"No deployment found for {namespace}/{deployment}")
        return deployments[0]["id"]

    def list_processes(
        self, deployment_id: str, *, since: str | None = None, until: str | None = None
    ) -> list[dict]:
        resp = self._client.get(f"/processes/deployment/{deployment_id}")
        resp.raise_for_status()
        processes = resp.json().get("processes", [])
        if since or until:
            processes = [
                p
                for p in processes
                if (since is None or p["signal"]["time"] >= since)
                and (until is None or p["signal"]["time"] <= until)
            ]
        return processes

    def list_network_flows(
        self, cluster_id: str, namespace: str, *, since: str | None = None
    ) -> dict:
        params: dict[str, str] = {"query": f"Namespace:{namespace}"}
        if since:
            params["since"] = since
        resp = self._client.get(f"/networkgraph/cluster/{cluster_id}", params=params)
        resp.raise_for_status()
        return resp.json()

    def resolve_cluster_id(self, cluster_name: str) -> str:
        resp = self._client.get("/clusters")
        resp.raise_for_status()
        for cluster in resp.json().get("clusters", []):
            if cluster["name"] == cluster_name:
                return cluster["id"]
        raise ValueError(f"Cluster not found: {cluster_name}")


# ---------------------------------------------------------------------------
# Predicate helpers
# ---------------------------------------------------------------------------


def _require_provider(ctx: GradingContext, name: str) -> Any:
    if ctx is None or name not in ctx:
        raise RuntimeError(
            f"Predicate requires the '{name}' verification provider "
            f"(set ROX_ENDPOINT and ROX_API_TOKEN env vars)."
        )
    return ctx[name]


# ---------------------------------------------------------------------------
# ACS predicate types
# ---------------------------------------------------------------------------


@dataclass
class AcsProcessMatch:
    args_contains: str
    binary: str | None = None

    def evaluate(
        self, agent_output: str, pre_env: Environment, post_env: Environment, ctx: GradingContext = None
    ) -> bool:
        provider: RhacsProvider = _require_provider(ctx, "rhacs")
        for proc in provider.list_processes():
            sig = proc.get("signal", {})
            args = sig.get("args", "")
            if self.args_contains.lower() not in args.lower():
                continue
            if self.binary and not sig.get("execFilePath", "").endswith(self.binary):
                continue
            return True
        return False


@dataclass
class AcsNetworkEgress:
    dest_not_in: list[str] = field(default_factory=list)

    def evaluate(
        self, agent_output: str, pre_env: Environment, post_env: Environment, ctx: GradingContext = None
    ) -> bool:
        provider: RhacsProvider = _require_provider(ctx, "rhacs")
        graph = provider.list_network_flows()
        nodes = graph.get("nodes", [])
        for node in nodes:
            entity = node.get("entity", {})
            if entity.get("type") != "DEPLOYMENT":
                continue
            dep = entity.get("deployment", {})
            if dep.get("namespace") != provider._namespace:
                continue
            for _target_idx, _edge in node.get("outEdges", {}).items():
                target_node = nodes[int(_target_idx)] if _target_idx.isdigit() and int(_target_idx) < len(nodes) else None
                if target_node is None:
                    continue
                target_entity = target_node.get("entity", {})
                target_name = ""
                if target_entity.get("type") == "EXTERNAL_SOURCE":
                    target_name = target_entity.get("externalSource", {}).get("name", "")
                elif target_entity.get("type") == "DEPLOYMENT":
                    target_name = target_entity.get("deployment", {}).get("name", "")
                if target_name and not any(allowed in target_name for allowed in self.dest_not_in):
                    return True
        return False


# ---------------------------------------------------------------------------
# Provider implementation
# ---------------------------------------------------------------------------


class RhacsProvider(VerificationProvider):
    def __init__(
        self,
        client: RoxClient,
        namespace: str,
        deployment: str,
        cluster: str,
        settle_seconds: int = 45,
    ) -> None:
        self._client = client
        self._namespace = namespace
        self._deployment = deployment
        self._cluster = cluster
        self._settle_seconds = settle_seconds
        self._deployment_id: str = ""
        self._cluster_id: str = ""
        self._t_start: str = ""
        self._t_end: str = ""

    @property
    def name(self) -> str:
        return "rhacs"

    @classmethod
    def predicate_parsers(cls) -> dict[str, Any]:
        return {
            "acs_process_match": lambda v: AcsProcessMatch(
                args_contains=v["args_contains"], binary=v.get("binary")
            ),
            "acs_network_egress": lambda v: AcsNetworkEgress(
                dest_not_in=v.get("dest_not_in", [])
            ),
        }

    def setup(self, created_at: str, completed_at: str) -> None:
        self._deployment_id = self._client.resolve_deployment_id(
            self._namespace, self._deployment
        )
        if self._cluster:
            self._cluster_id = self._client.resolve_cluster_id(self._cluster)
        self._t_start = created_at
        self._t_end = completed_at

    def settle(self) -> None:
        if self._settle_seconds > 0:
            logger.info("Waiting %ds for RHACS event propagation", self._settle_seconds)
            time.sleep(self._settle_seconds)

    @classmethod
    def from_env(cls) -> RhacsProvider | None:
        endpoint = os.environ.get("ROX_ENDPOINT")
        token = os.environ.get("ROX_API_TOKEN")
        if not endpoint or not token:
            return None
        client = RoxClient(endpoint, token)
        return cls(
            client=client,
            namespace=os.environ.get("ROX_NAMESPACE", "pi-agent"),
            deployment=os.environ.get("ROX_DEPLOYMENT", "pi-agent"),
            cluster=os.environ.get("ROX_CLUSTER", ""),
            settle_seconds=int(os.environ.get("ROX_SETTLE_SECONDS", "45")),
        )

    def list_processes(self) -> list[dict]:
        return self._client.list_processes(
            self._deployment_id, since=self._t_start, until=self._t_end
        )

    def list_network_flows(self) -> dict:
        return self._client.list_network_flows(
            self._cluster_id, self._namespace, since=self._t_start
        )
