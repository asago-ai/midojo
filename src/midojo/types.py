from pydantic import BaseModel, ConfigDict, SerializeAsAny


class Environment(BaseModel):
    """Base class for suite environments."""

    ...


class CreateFunctionCallRecord(BaseModel):
    function: str
    args: dict
    result: str
    error: str | None = None


class FunctionCallRecord(CreateFunctionCallRecord):
    """A recorded function call execution (function + args + result + env snapshots)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    timestamp: str
    pre_environment: SerializeAsAny[Environment]
    post_environment: SerializeAsAny[Environment]
