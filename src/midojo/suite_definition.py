"""Validated suite data, separate from runtime construction and evaluation.

Environment state and verifier arguments remain extensible. Their
implementations validate the parts specific to each plugin.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, field_validator, model_validator

from midojo.types import SuiteName


class _DefinitionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OpenShellRuntimeDefinition(_DefinitionModel):
    """Runs the agent in an OpenShell sandbox created for each evaluation."""

    type: Literal["openshell"] = "openshell"
    image: str = Field(min_length=1)
    agent_command: list[str] | None = None
    policy: dict[str, Any] | None = None
    providers: list[str] = Field(default_factory=list)
    env_vars: dict[str, str] = Field(default_factory=dict)
    # Seeded into the sandbox; relative paths land under /sandbox/workdir.
    files: dict[str, str] = Field(default_factory=dict)


class UnmanagedRuntimeDefinition(_DefinitionModel):
    """The agent runs somewhere MiDojo doesn't control."""

    type: Literal["unmanaged"]


def _runtime_type(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("type", "openshell")
    return getattr(value, "type", None)


AgentRuntimeDefinition = Annotated[
    Annotated[OpenShellRuntimeDefinition, Tag("openshell")] | Annotated[UnmanagedRuntimeDefinition, Tag("unmanaged")],
    Discriminator(_runtime_type),
]


class ProbeDefinition(_DefinitionModel):
    """Exactly one non-null payload or source; empty inline payloads are valid."""

    payload: str | None = None
    source: str | None = None
    index: int = Field(default=0, ge=0)
    attack_type: str = "verbatim"

    @model_validator(mode="after")
    def exactly_one_payload_or_source(self) -> Self:
        if (self.payload is None) == (self.source is None):
            raise ValueError("exactly one of 'payload' or 'source' is required")
        return self


class UserTaskDefinition(_DefinitionModel):
    id: str = Field(min_length=1)
    prompt: str
    utility: dict[str, Any]


class InjectionTaskDefinition(_DefinitionModel):
    id: str = Field(min_length=1)
    description: str
    probes: dict[str, ProbeDefinition] = Field(default_factory=dict)
    security: dict[str, Any]


class SuiteDefinition(_DefinitionModel):
    """Suite name plus the contents of suite.yaml, validated before setup."""

    name: SuiteName
    agent_runtime: AgentRuntimeDefinition
    environment: dict[str, Any] = Field(default_factory=dict)
    user_tasks: list[UserTaskDefinition] = Field(default_factory=list)
    injection_tasks: list[InjectionTaskDefinition] = Field(default_factory=list)

    @field_validator("user_tasks", "injection_tasks")
    @classmethod
    def unique_task_ids(
        cls, tasks: list[UserTaskDefinition] | list[InjectionTaskDefinition]
    ) -> list[UserTaskDefinition] | list[InjectionTaskDefinition]:
        seen: set[str] = set()
        for task in tasks:
            if task.id in seen:
                raise ValueError(f"duplicate task ID: {task.id!r}")
            seen.add(task.id)
        return tasks
