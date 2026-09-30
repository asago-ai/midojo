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

from pydantic import BaseModel

_OBSERVATION_TYPES: dict[str, type[BaseModel]] = {}


def register_observation_type(source: str, model: type[BaseModel]) -> None:
    """Register the model that a source's observations must match."""
    if _OBSERVATION_TYPES.get(source, model) is not model:
        raise ValueError(f"Observation source {source!r} is already registered")
    _OBSERVATION_TYPES[source] = model


def observation_type(source: str) -> type[BaseModel] | None:
    """The model registered for a source, or None if the source is unknown."""
    return _OBSERVATION_TYPES.get(source)
