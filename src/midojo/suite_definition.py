"""Validated suite data, separate from backend construction and evaluation.

Backend options, environment state, and verifier arguments remain extensible.
Their runtime implementations validate the parts specific to each plugin.
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from midojo.types import SuiteName


class _DefinitionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BackendDefinition(_DefinitionModel):
    """Object form of a backend selector; options belong to the backend."""

    model_config = ConfigDict(extra="allow")

    type: str = Field(min_length=1)


class EnvironmentDefinition(_DefinitionModel):
    """Common environment fields, with additional fields owned by backends."""

    model_config = ConfigDict(extra="allow")

    backend: str | BackendDefinition = "dict"
    state: dict[str, Any] = Field(default_factory=dict)


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
    environment: EnvironmentDefinition
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
