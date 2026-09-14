"""Runtime evaluation context shared by agent integrations and SDK hooks."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from starlette.types import ASGIApp, Receive, Scope, Send

SESSION_HEADER = "X-Midojo-Session"
_session_token: ContextVar[str | None] = ContextVar("midojo_session_token", default=None)


class MissingSessionError(RuntimeError):
    pass


def session_token(explicit: str | None = None) -> str:
    token = explicit or _session_token.get() or os.environ.get("MIDOJO_SESSION_TOKEN")
    if not token:
        raise MissingSessionError(
            "No MiDojo evaluation session. Set MIDOJO_SESSION_TOKEN or establish session_context()."
        )
    return token


def session_headers(token: str | None = None) -> dict[str, str]:
    """Forward context to an agent or MCP server without replacing its own auth."""
    return {SESSION_HEADER: session_token(token)}


@contextmanager
def session_context(token: str | None) -> Iterator[None]:
    """Bind callbacks to one task; nested and concurrent tasks retain their own context."""
    marker = _session_token.set(token)
    try:
        yield
    finally:
        _session_token.reset(marker)


class MidojoSessionMiddleware:
    """ASGI entry point for persistent agents receiving X-Midojo-Session per task.

    Install on the agent application, not on the MiDojo control plane. Queued
    work must carry the token explicitly if it outlives the request's task tree.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        raw = headers.get(SESSION_HEADER.lower().encode())
        with session_context(raw.decode("latin-1") if raw else None):
            await self.app(scope, receive, send)
