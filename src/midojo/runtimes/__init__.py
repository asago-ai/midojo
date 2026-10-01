"""Agent runtimes: where a suite's agent runs and how MiDojo observes it.

A suite declares its runtime under ``agent_runtime`` in ``suite.yaml``:

  * ``openshell`` (the default) — :class:`~midojo.runtimes.openshell.OpenShellRuntime`
    creates an OpenShell sandbox for each evaluation, seeds its files, and
    collects runtime observations from outside the agent.
  * ``unmanaged`` (experimental) — :class:`UnmanagedRuntime`. The agent runs
    somewhere MiDojo doesn't control and nothing is observed outside it.

The orchestrator drives every runtime through the :class:`AgentRuntime`
lifecycle. The world state the agent's tools read and write is the suite's
``environment``, which the control plane keeps whatever the runtime.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from midojo.runtimes.openshell import OpenShellRuntime
from midojo.suite_definition import AgentRuntimeDefinition, OpenShellRuntimeDefinition


class AgentRuntime(Protocol):
    """The lifecycle the orchestrator drives around a benchmark run and each evaluation."""

    name: str

    def start_run(self, run_id: str, *, suite_name: str) -> str | None:
        """Open the run's resources. Returns a description of them for the run log, or None."""
        ...

    def setup(
        self,
        injections: dict[str, str],
        *,
        session_token: str,
        eval_id: str,
        user_task_id: str,
        injection_task_id: str | None,
    ) -> None:
        """Prepare the agent for one evaluation, with the active injections in place."""
        ...

    def observe(self) -> dict[str, BaseModel]:
        """The evaluation's runtime observations, keyed by source."""
        ...

    def teardown(self) -> None:
        """Release the evaluation's resources, including after a failed ``setup``."""
        ...

    def end_run(self) -> None:
        """Release the run's resources."""
        ...


class UnmanagedRuntime:
    """An agent that MiDojo neither starts nor observes.

    ``midojo-run`` reaches it at ``--agent-uri`` over ``--protocol``, and each task
    carries the evaluation session (see :mod:`midojo.agent_client`). Every
    lifecycle step is a no-op.
    """

    name = "unmanaged"

    def start_run(self, run_id: str, *, suite_name: str) -> None:
        return None

    def setup(
        self,
        injections: dict[str, str],
        *,
        session_token: str,
        eval_id: str,
        user_task_id: str,
        injection_task_id: str | None,
    ) -> None:
        pass

    def observe(self) -> dict[str, BaseModel]:
        return {}

    def teardown(self) -> None:
        pass

    def end_run(self) -> None:
        pass


def build_runtime(suite_name: str, definition: AgentRuntimeDefinition) -> AgentRuntime:
    """Construct the runtime a suite declares."""
    if isinstance(definition, OpenShellRuntimeDefinition):
        return OpenShellRuntime(
            suite_name,
            image=definition.image,
            policy=definition.policy,
            providers=definition.providers,
            env_vars=definition.env_vars,
            agent_command=definition.agent_command,
            files=definition.files,
        )
    return UnmanagedRuntime()
