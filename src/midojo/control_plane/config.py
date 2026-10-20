"""Configuration for a control-plane application instance."""

from pydantic import BaseModel, Field

# Environment variable that sets the control token for midojo-serve and midojo-run.
CONTROL_TOKEN_ENV = "MIDOJO_CONTROL_TOKEN"


class AppConfig(BaseModel):
    session_ttl_seconds: int = Field(default=3600, gt=0)
    # Bearer token required on every route except /agent and /health. None leaves them open.
    control_token: str | None = Field(default=None, min_length=1)
