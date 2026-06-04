"""OpenShell environment backend (scaffold).

A container backend that provisions a sandboxed shell environment on NVIDIA
OpenShell (https://github.com/NVIDIA/OpenShell). Unlike the dict backend — whose
"environment" is an in-memory model — OpenShell's environment is a real Linux
sandbox: the agent runs *inside* it (e.g. ``--from pi``), governed by a policy,
and the kernel audits everything it does as OCSF events.

Two observation channels map onto the engine's grading inputs:
  * **workspace diff** — the seeded ``/sandbox`` files before vs. after the
    session — is the pre/post environment (graded by ordinary env predicates).
  * **OCSF events** — network/process/finding events from the sandbox's policy
    enforcement — are runtime observations (graded by an ``openshell`` verifier).

Status: ``provision()`` (workspace rendering) is real and tested. The live
sandbox lifecycle (``setup``/``snapshot``/``observations``/``teardown``) is
scaffolded against the OpenShell gRPC SDK and is **not yet exercised** — it
needs the Phase-2 eval-lifecycle plumbing (the control plane calling
setup/teardown and routing observations into grading) and a live gateway to run
against. The method bodies document the intended gRPC mapping.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from midojo.probes import substitute_probes
from midojo.types import Environment


class OpenShellEnvironment(Environment):
    """Observable state of an OpenShell sandbox.

    ``workspace_files`` is the pre/post snapshot of seeded files; ``files_created``
    is the post-session workspace diff. Runtime evidence (OCSF network/process
    events) is *not* env state — it flows through ``observations``, read by an
    ``openshell`` verifier, not stored here.
    """

    workspace_files: dict[str, str] = Field(default_factory=dict)
    files_created: list[str] = Field(default_factory=list)


class OpenShellBackend:
    """Provisions an OpenShell sandbox from a suite's image + policy + workspace.

    Suite YAML::

        environment:
          backend:               # infra config lives inside the backend
            type: openshell
            image: pi            # OpenShell sandbox image / --from target
            policy: pi           # optional named/inline OPA policy
          state:                 # seeded workspace files (probe placeholders allowed)
            customer_report.txt: "Q4 report ... {injection_task_0:main}"
    """

    def __init__(
        self,
        suite_name: str,
        *,
        image: str | None,
        policy: str | None = None,
        workspace: dict[str, str] | None = None,
    ) -> None:
        if not image:
            raise ValueError("openshell backend requires an 'image' field under 'environment.backend'")
        self._suite_name = suite_name
        self._image: str = image
        self._policy = policy
        self._workspace: dict[str, str] = workspace or {}
        # The live sandbox handle, set by setup() for the active evaluation.
        # Evals run sequentially (see app.state), so a single handle is safe.
        self._sandbox: Any = None

    @property
    def environment_type(self) -> type[Environment]:
        return OpenShellEnvironment

    def provision(self, injections: dict[str, str]) -> Environment:
        """Render the seeded workspace with the active injections substituted.

        Returns the pre-session environment. Seeding it into a live sandbox is
        setup()'s job (Phase 2); this stays pure so suites load without a gateway.
        """
        files = {path: substitute_probes(template, injections) for path, template in self._workspace.items()}
        return OpenShellEnvironment(workspace_files=files)

    # --- Live sandbox lifecycle (scaffold; Phase-2 plumbing will call these) ---

    @staticmethod
    def _sandbox_client() -> Any:
        try:
            from openshell import SandboxClient  # pyright: ignore[reportMissingImports]
        except ImportError as e:  # pragma: no cover - exercised only with the SDK installed
            raise RuntimeError(
                "The 'openshell' SDK is required for the OpenShell backend. Install it with `uv pip install openshell`."
            ) from e
        return SandboxClient()

    def setup(self, environment: OpenShellEnvironment) -> None:
        """Create the sandbox from the image+policy and seed the workspace.

        gRPC mapping: ``CreateSandbox(spec)`` then ``ExecSandbox`` to write each
        ``workspace_files`` entry under ``/sandbox`` and drop a baseline marker.
        """
        raise NotImplementedError("OpenShell sandbox provisioning is not wired yet (Phase 2).")

    def snapshot(self) -> OpenShellEnvironment:
        """Read the post-session workspace back (diff vs. the seeded baseline).

        gRPC mapping: ``ExecSandbox(['find /sandbox -newer .baseline'])`` + read.
        """
        raise NotImplementedError("OpenShell workspace snapshot is not wired yet (Phase 2).")

    def observations(self) -> dict[str, Any]:
        """Fetch OCSF runtime events for the session.

        gRPC mapping: ``GetSandboxLogs`` (raw proto stub — no high-level wrapper),
        filtered to ``level == "OCSF"`` and parsed into network/process/finding
        events for the ``openshell`` verifier.
        """
        raise NotImplementedError("OpenShell OCSF observations are not wired yet (Phase 2).")

    def teardown(self) -> None:
        """Destroy the sandbox. gRPC mapping: ``DeleteSandbox``."""
        raise NotImplementedError("OpenShell sandbox teardown is not wired yet (Phase 2).")
