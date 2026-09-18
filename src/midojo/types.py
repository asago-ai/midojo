from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, StringConstraints

from midojo.channels import Channel, InjectionMode

# A suite name is also a URL path segment. Dots support external module paths;
# a leading alphanumeric character rules out the special '.' and '..' segments.
SuiteName = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]


class Environment(BaseModel):
    """Base class for suite environments."""

    ...


class FunctionCallRecord(BaseModel):
    """A recorded function call execution (function + args + result + env snapshots)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    function: str
    args: dict
    result: str
    error: str | None = None
    timestamp: str
    pre_environment: SerializeAsAny[Environment]
    post_environment: SerializeAsAny[Environment]


class InjectionTarget(BaseModel):
    """Which part of a channel's content a payload lands in.

    ``None`` means unconstrained: any tool, and a field the adapter picks.
    Fields are added here as channels need them.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str | None = None
    field: str | None = None


class InjectionInstruction(BaseModel):
    """One payload, the channel it enters through, and how it is applied.

    Built from a suite's probes at load time and stored on an evaluation as
    its *injection plan*; interception adapters read the plan and deliver the
    payload. ``probe_key`` (``"<task_id>:<probe_id>"``) ties a delivered
    payload back to the probe that declared it.
    """

    model_config = ConfigDict(extra="forbid")

    channel: Channel
    probe_key: str
    payload: str
    target: InjectionTarget = Field(default_factory=InjectionTarget)
    mode: InjectionMode = InjectionMode.APPEND
