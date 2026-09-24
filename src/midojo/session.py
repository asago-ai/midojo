"""Experimental request-header transport for development agent integrations."""

SESSION_HEADER = "X-Midojo-Session"


def session_headers(token: str) -> dict[str, str]:
    """Experimental helper to forward context to an agent or MCP server."""
    return {SESSION_HEADER: token}
