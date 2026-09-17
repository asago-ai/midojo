"""Evaluation-session transport used by the orchestrator's agent clients."""

SESSION_HEADER = "X-Midojo-Session"


def session_headers(token: str) -> dict[str, str]:
    """Forward the evaluation token without replacing the agent's own auth."""
    return {SESSION_HEADER: token}
