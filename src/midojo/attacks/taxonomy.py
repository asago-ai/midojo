"""OWASP Top 10 for Agentic Applications (ASI) — December 2025.

The categorization spine for the attack library. An attack is tagged with the
OWASP ASI risk category (or categories) it exercises, so the catalog can be
queried and coverage measured by risk class.

These definitions are lifted verbatim from Sai Chandra Pandraju's
``agentdojo-owasp`` red-team extensions (``src/agentdojo/redteam/asi.py``) so
the two catalogs share one taxonomy and his existing tags import directly.

Reference: OWASP GenAI Security Project — Agentic Security Initiative,
"OWASP Top 10 for Agentic Applications 2026" (CC BY-SA 4.0).
"""

from __future__ import annotations

import enum


class ASICategory(str, enum.Enum):
    """OWASP Top 10 for Agentic Applications risk categories."""

    ASI_01 = "ASI-01"
    ASI_02 = "ASI-02"
    ASI_03 = "ASI-03"
    ASI_04 = "ASI-04"
    ASI_05 = "ASI-05"
    ASI_06 = "ASI-06"
    ASI_07 = "ASI-07"
    ASI_08 = "ASI-08"
    ASI_09 = "ASI-09"
    ASI_10 = "ASI-10"


ASI_DESCRIPTIONS: dict[ASICategory, str] = {
    ASICategory.ASI_01: "Agent Goal Hijack",
    ASICategory.ASI_02: "Tool Misuse and Exploitation",
    ASICategory.ASI_03: "Identity and Privilege Abuse",
    ASICategory.ASI_04: "Agentic Supply Chain Vulnerabilities",
    ASICategory.ASI_05: "Unexpected Code Execution",
    ASICategory.ASI_06: "Memory and Context Poisoning",
    ASICategory.ASI_07: "Insecure Inter-Agent Communication",
    ASICategory.ASI_08: "Cascading Failures",
    ASICategory.ASI_09: "Human Agent Trust Exploitation",
    ASICategory.ASI_10: "Rogue Agents",
}

ASI_DETAILS: dict[ASICategory, str] = {
    ASICategory.ASI_01: (
        "Adversary redirects agent from intended task via prompt injection, "
        "indirect injection through tools, or instruction override."
    ),
    ASICategory.ASI_02: (
        "Agent uses tools in unintended ways — wrong tools, unsafe parameters, "
        "recursive loops, budget exhaustion."
    ),
    ASICategory.ASI_03: (
        "Agent impersonates other agents, escalates permissions, "
        "exploits authorization boundaries, or leaks its system prompt."
    ),
    ASICategory.ASI_04: (
        "Malicious content in dependencies the agent consumes — poisoned MCP servers, "
        "compromised tool metadata, tainted retrieval documents."
    ),
    ASICategory.ASI_05: ("Agent generates or executes unauthorized shell commands, SQL, or code."),
    ASICategory.ASI_06: (
        "Adversary plants false information in agent memory/context "
        "that persists across turns or sessions."
    ),
    ASICategory.ASI_07: ("Message spoofing, injection, or MITM between agents in multi-agent systems."),
    ASICategory.ASI_08: ("One agent's error/hallucination propagates through downstream agents or tool chains."),
    ASICategory.ASI_09: (
        "Agent generates authoritative-sounding but wrong information, "
        "leading humans to make bad decisions."
    ),
    ASICategory.ASI_10: ("Agent drifts from objectives autonomously — goal drift, reward hacking, runaway autonomy."),
}


def parse_asi_category(value: str | ASICategory) -> ASICategory:
    """Coerce a code string (e.g. ``"ASI-01"``) or member to an ``ASICategory``."""
    if isinstance(value, ASICategory):
        return value
    try:
        return ASICategory(value)
    except ValueError:
        known = [c.value for c in ASICategory]
        raise ValueError(f"Unknown OWASP ASI category '{value}'. Known categories: {known}") from None
