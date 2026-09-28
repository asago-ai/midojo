"""The OpenShell SDK internals MiDojo depends on, kept in one place.

The public Python SDK (``openshell`` 0.1.2) cannot yet do two things the
backend needs, so these functions use SDK internals:

* **Build a sandbox spec with policy and providers.** ``SandboxClient.create``
  takes an ``openshell_pb2.SandboxSpec``, but that type is only importable from
  the private ``openshell._proto`` package. OpenShell's own Python e2e tests
  import it the same way. The Rust and Go SDKs expose the spec as a public type.
* **Read a sandbox's logs.** The Python SDK has no logs or watch method, so the
  request goes through the client's private gRPC stub. The Rust SDK has a
  public ``watch_logs``.

Nothing else in MiDojo should import ``openshell._proto`` or touch
``SandboxClient._stub``. When the public SDK gains these capabilities, replace
the functions here and delete this module.

The ``openshell`` package is an optional dependency, so every import is lazy.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def apply_policy(policy: dict | None, spec: Any) -> None:
    """Populate ``spec.policy`` from a camelCase proto-JSON dict. ``None`` is a no-op.

    Leaving the policy unset lets the sandbox use the policy baked into its
    image, or OpenShell's restrictive default.
    """
    if policy is None:
        return
    from google.protobuf.json_format import ParseDict  # protobuf is a required dependency

    ParseDict(policy, spec.policy)


def build_sandbox_spec(
    *,
    image: str,
    environment: Mapping[str, str],
    providers: Iterable[str],
    policy: dict | None,
) -> Any:
    """Build the ``SandboxSpec`` passed to ``SandboxClient.create``.

    Private because ``SandboxSpec`` is only importable from ``openshell._proto``.
    Replace with public spec types, or policy and provider arguments on
    ``SandboxClient.create``, once the Python SDK offers them.
    """
    from openshell._proto import openshell_pb2  # pyright: ignore[reportMissingImports]

    spec = openshell_pb2.SandboxSpec(
        template=openshell_pb2.SandboxTemplate(image=image),
        environment=dict(environment),
        providers=list(providers),
    )
    apply_policy(policy, spec)
    return spec


def read_ocsf_messages(
    client: Any,
    *,
    sandbox: str,
    workspace: str,
    since_ms: int,
    timeout_seconds: float = 10.0,
) -> list[str]:
    """Return the OCSF messages a sandbox's supervisor has pushed since ``since_ms``.

    Private because the Python SDK has no logs API; this calls
    ``GetSandboxLogs`` through ``client._stub``. Replace with a public
    ``SandboxClient`` logs or watch method (the equivalent of the Rust SDK's
    ``watch_logs``) once one exists.
    """
    from google.protobuf.timestamp_pb2 import Timestamp
    from openshell._proto import datamodel_pb2, openshell_pb2  # pyright: ignore[reportMissingImports]

    since = Timestamp()
    since.FromMilliseconds(since_ms)
    response = client._stub.GetSandboxLogs(
        openshell_pb2.GetSandboxLogsRequest(
            sandbox=sandbox,
            workspace_scope=datamodel_pb2.WorkspaceSelector(workspace=workspace),
            since_time=since,
            sources=["sandbox"],
        ),
        timeout=timeout_seconds,
    )
    return [line.message for line in response.logs if line.level.upper() == "OCSF"]
