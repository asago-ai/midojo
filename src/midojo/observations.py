"""Runtime observation types, keyed by source.

Runtime observations are evidence collected outside the agent, such as
OpenShell's workdir diff and OCSF events. Each source registers the Pydantic
model its observations must match. The control plane validates recorded
observations against that model and rejects unknown sources, so verifiers
receive typed models instead of raw JSON.

A backend registers its source when its module is imported::

    register_observation_type("openshell", OpenShellObservations)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_OBSERVATION_TYPES: dict[str, type[BaseModel]] = {}


def register_observation_type(source: str, model: type[BaseModel]) -> None:
    """Register the model that a source's observations must match."""
    if _OBSERVATION_TYPES.get(source, model) is not model:
        raise ValueError(f"Observation source {source!r} is already registered")
    _OBSERVATION_TYPES[source] = model


def observation_type(source: str) -> type[BaseModel] | None:
    """The model registered for a source, or None if the source is unknown."""
    return _OBSERVATION_TYPES.get(source)


# Key of the OpenShell entry in an evaluation's runtime observations.
OBSERVATIONS_SOURCE = "openshell"


class ProcessRecord(BaseModel):
    """A process OCSF saw launch in the sandbox."""

    model_config = ConfigDict(extra="forbid")

    binary: str
    pid: int
    command: str | None = None  # the launched command line, when OCSF logged it
    exit_code: int | None = None  # None when no PROC:TERMINATE event was logged


class OpenShellObservations(BaseModel):
    """What OpenShell saw the agent do during one evaluation.

    Collected by ``OpenShellRuntime.observe()`` outside the agent, and recorded
    by the orchestrator as ``observations["openshell"]``. It lives here rather
    than in :mod:`midojo.runtimes.openshell` so verifiers and graders can read it
    without importing the OpenShell SDK; the runtime re-exports it.
    """

    model_config = ConfigDict(extra="forbid")

    # Workdir diff against the seeded files (absolute paths)
    files_created: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    files_deleted: list[str] = Field(default_factory=list)
    workdir_new_file_contents: dict[str, str] = Field(default_factory=dict)

    # OCSF events (kernel-verified)
    processes: list[ProcessRecord] = Field(default_factory=list)  # in launch order
    network_calls_allowed: list[str] = Field(default_factory=list)  # "host:port"
    network_calls_blocked: list[str] = Field(default_factory=list)  # "host:port", or "host" for DNS refusals
    # Closed because the sandbox's policy changed mid-connection, not denied by policy
    network_calls_interrupted: list[str] = Field(default_factory=list)
    # Sandbox-verified executables that made allowed or blocked network calls
    network_callers: list[str] = Field(default_factory=list)
    security_findings: list[str] = Field(default_factory=list)  # finding titles


register_observation_type(OBSERVATIONS_SOURCE, OpenShellObservations)
