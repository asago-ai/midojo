"""Environment backends — the first of the engine's two observability axes.

A backend defines *what the agent operates on*. Today there is one: a state
dict declared in ``suite.yaml`` and inferred into a Pydantic model
(:class:`DictEnvironmentBackend`). The protocol is the seam where richer
backends plug in later — a sandboxed container (e.g. NVIDIA OpenShell), or an
eventually a full cluster resource — without the suite, control plane, or
grading code needing to know which backend is in play.

A backend is responsible for:
  * the *type* of the observable state (so the control plane can validate
    env reads/writes against a concrete schema), and
  * *provisioning* a fresh instance of that state for an evaluation, with the
    active injection payloads templated in.

Future protocol extensions (Phase 2+): ``snapshot()`` for pre/post capture,
``observations()`` to surface event streams (process/network/k8s) that
verification providers consume, and ``teardown()`` for lifecycle cleanup.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

import yaml

from midojo.env_inference import infer_environment_type
from midojo.probes import substitute_probes
from midojo.types import Environment


@runtime_checkable
class EnvironmentBackend(Protocol):
    """Provisions and types the observable state an agent operates on."""

    @property
    def environment_type(self) -> type[Environment]:
        """Concrete Pydantic type of the observable state."""
        ...

    def provision(self, injections: dict[str, str]) -> Environment:
        """Build a fresh environment instance with ``injections`` templated in."""
        ...


class DictEnvironmentBackend:
    """Default backend: a declared state dict from ``suite.yaml``.

    The dict is inferred into a Pydantic model once at load time; each
    :meth:`provision` re-renders the declared state (substituting the active
    probe payloads) and validates it into a fresh instance.
    """

    def __init__(
        self,
        suite_name: str,
        env_raw: dict,
        environment_type: type[Environment] | None = None,
    ) -> None:
        self._env_raw = env_raw
        self._environment_type = environment_type or infer_environment_type(suite_name, env_raw)

    @property
    def environment_type(self) -> type[Environment]:
        return self._environment_type

    def provision(self, injections: dict[str, str]) -> Environment:
        env_text = yaml.dump(self._env_raw, default_flow_style=False, default_style='"')
        env_text = substitute_probes(env_text, injections)
        return self._environment_type.model_validate(yaml.safe_load(env_text))


# --- Backend registry + dispatch ---
#
# Mirrors the verification-provider registry: a suite's ``environment.backend``
# field selects which factory builds the backend, so new backends register
# instead of editing the suite loader. A factory receives the suite name and
# the full ``environment`` block (so it can read its own backend-specific keys).

BackendFactory = Callable[[str, dict], EnvironmentBackend]

_BACKENDS: dict[str, BackendFactory] = {}


def register_backend(name: str, factory: BackendFactory) -> None:
    if name in _BACKENDS:
        raise ValueError(f"Environment backend {name!r} is already registered")
    _BACKENDS[name] = factory


def build_backend(suite_name: str, env_config: dict) -> EnvironmentBackend:
    """Construct the backend declared by ``env_config['backend']`` (default: dict)."""
    name = env_config.get("backend", "dict")
    factory = _BACKENDS.get(name)
    if factory is None:
        raise ValueError(f"Unknown environment backend: {name!r}. Registered: {sorted(_BACKENDS)}")
    return factory(suite_name, env_config)


def _build_dict_backend(suite_name: str, env_config: dict) -> EnvironmentBackend:
    if "state" not in env_config:
        raise ValueError("dict environment backend requires a 'state' field under 'environment'")
    return DictEnvironmentBackend(suite_name, env_config["state"])


register_backend("dict", _build_dict_backend)
