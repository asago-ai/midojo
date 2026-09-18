"""Delivery channels — where an injection payload enters the agent.

A *channel* names the point at which a payload reaches the agent under test.
It is the engine's third axis, alongside environment backends (*what the agent
operates on*) and verifiers (*how outcomes are checked*).

Every channel here is **adapter-delivered**: an interception layer (a fake MCP
server, a PI extension, a coding-agent hook) reads the evaluation's injection
plan and applies the instruction. That is deliberately distinct from the
placeholder substitution the control plane performs on environment state and
user-task prompts, which needs no adapter and stays on a probe's default
(no ``channel``) path. The split keeps one invariant worth relying on: a probe
is delivered by substitution *or* by an adapter, never both.

The set is closed for now. Adding a member is not a breaking change; a
registry, mirroring :mod:`midojo.verifiers`, is the likely endgame once
out-of-tree suites need channels the engine does not ship.
"""

from __future__ import annotations

import enum


class Channel(str, enum.Enum):
    """Where an injection payload enters the agent."""

    TOOL_RESULT = "tool_result"
    TOOL_DESCRIPTION = "tool_description"


class InjectionMode(str, enum.Enum):
    """How a payload is combined with the content it is delivered into.

    ``append`` is the default because it is the only mode that always works:
    ``embed`` needs a structured response to splice a field into, and silently
    degrades to appending when the tool returns prose.
    """

    APPEND = "append"
    EMBED = "embed"
    REPLACE = "replace"
    NEW_FIELD = "new_field"


def parse_channel(value: str | Channel) -> Channel:
    """Coerce a channel name (e.g. ``"tool_result"``) to a :class:`Channel`."""
    if isinstance(value, Channel):
        return value
    try:
        return Channel(value)
    except ValueError:
        known = [c.value for c in Channel]
        raise ValueError(f"Unknown channel '{value}'. Known channels: {known}") from None


def parse_mode(value: str | InjectionMode) -> InjectionMode:
    """Coerce a mode name (e.g. ``"embed"``) to an :class:`InjectionMode`."""
    if isinstance(value, InjectionMode):
        return value
    try:
        return InjectionMode(value)
    except ValueError:
        known = [m.value for m in InjectionMode]
        raise ValueError(f"Unknown injection mode '{value}'. Known modes: {known}") from None
