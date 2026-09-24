"""Configuration for a control-plane application instance."""

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    session_ttl_seconds: int = Field(default=3600, gt=0)
