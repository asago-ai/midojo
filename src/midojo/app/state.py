"""Process-local application state.

Persistence is in-memory only (lost on restart). A db store may replace
this layer later.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from midojo.types import Environment
from midojo.verification import VerificationProvider
from midojo.yaml_task_suite import YAMLTaskSuite

from .models import FunctionCallRecord


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


# --- State models ---


@dataclass
class Evaluation:
    """A single task execution within a Run. Captures the environment before and after tool execution, the function call trace, and grading results."""

    id: str
    user_task_id: str
    injection_task_id: str | None
    pre_environment: Environment
    environment: Environment
    function_calls: list[FunctionCallRecord] = field(default_factory=list)
    agent_input: str | None = None
    agent_output: str | None = None
    completed: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    active_injections: dict[str, str] = field(default_factory=dict)
    utility: bool | None = None
    security: bool | None = None


class Run(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    evaluations: dict[str, Evaluation] = {}
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# --- Module-level state ---

suite: YAMLTaskSuite = None  # type: ignore[assignment]
providers: dict[str, VerificationProvider] = {}
runs: dict[str, Run] = {}
# Only one eval is active at a time — the orchestrator runs tasks sequentially.
# Concurrent evals would clobber this; use explicit /runs/{id}/evaluations/{id}/* routes instead.
current_eval: Evaluation | None = None
