"""Parse OpenShell OCSF log events from sandbox log lines.

OCSF shorthand formats emitted by OpenShell 0.1 (openshell-ocsf/src/format/shorthand.rs),
as observed on a live 0.1.2 gateway:

  Network (transparent TCP; the caller is the sandbox-verified executable path, and the
  pid is 0 because it is not visible across the sandbox boundary):
    NET:OPEN [INFO] ALLOWED /usr/bin/bash(0) -> example.com:80 [policy:web engine:opa]
    NET:OPEN [MED] DENIED /usr/bin/bash(0) -> audit.ext-log.com:443 [reason:transparent_tcp_policy_denied]

  Network (DNS-stage refusal; no caller and no port):
    NET:REFUSE [MED] DENIED audit.ext-log.com [reason:policy_dns_ineligible]

  HTTP (L7-inspected endpoints; no caller):
    HTTP:GET [INFO] ALLOWED GET http://example.com/

  Process (only for the sandbox's main process; commands run through exec emit none):
    PROC:LAUNCH [INFO] python3(42) [cmd:python3 /workspace/exploit.py]
    PROC:TERMINATE [INFO] python3(42) [exit:0]

  Security findings:
    FINDING:BLOCKED [HIGH] "NSSH1 Nonce Replay Attack" [confidence:high]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Message patterns (derived from openshell-ocsf/src/format/shorthand.rs)
# ---------------------------------------------------------------------------

# The caller ("<exe>(<pid>) -> ") and the port are optional: DNS-stage refusals
# carry neither.
_NET_PATTERN = re.compile(
    r"NET:\w+\s+\[\w+\]\s+(ALLOWED|DENIED)\s+(?:(\S+)\s+->\s+)?([\w.\-]+)(?::(\d+))?",
    re.IGNORECASE,
)

_HTTP_PATTERN = re.compile(
    r"HTTP:(\w+)\s+\[\w+\]\s+(ALLOWED|DENIED)\s+(?:\S+\s+->\s+)?(\w+)\s+(https?://\S+)",
    re.IGNORECASE,
)

_CALLER_PID_SUFFIX = re.compile(r"\(\d+\)$")

# A connection closed because the supervisor installed a newer policy generation
# while it was open. OpenShell reports it as a denial, but it is not a policy
# decision about the destination: the client typically retries under the new
# generation. Observed on 0.1.2 shortly after sandbox start:
#   NET:OPEN [MED] DENIED host.openshell.internal:8321 [reason:L7 tunnel closed before
#   inspection because policy changed: policy generation is stale [captured_generation:1 ...]]
_STALE_GENERATION_REASON = "policy generation is stale"

_PROC_LAUNCH_PATTERN = re.compile(
    r"PROC:LAUNCH\s+\[\w+\]\s+(\S+)\((\d+)\)(?:\s+\[cmd:(.+?)\])?",
    re.IGNORECASE,
)

_PROC_TERMINATE_PATTERN = re.compile(
    r"PROC:TERMINATE\s+\[\w+\]\s+(\S+)\((\d+)\)(?:\s+\[exit:(-?\d+)\])?",
    re.IGNORECASE,
)

_FINDING_PATTERN = re.compile(
    r'FINDING:(\w+)\s+\[\w+\]\s+"([^"]+)"',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Parsed event types
# ---------------------------------------------------------------------------


@dataclass
class NetworkEvent:
    action: str  # "ALLOWED" or "DENIED"
    process: str | None  # "/usr/bin/curl(0)"; None for DNS-stage refusals
    host: str  # "audit.ext-log.com"
    port: int | None  # None for DNS-stage refusals
    endpoint: str  # "audit.ext-log.com:443", or "audit.ext-log.com" without a port
    raw: str

    @property
    def binary(self) -> str | None:
        """Calling executable without the pid suffix, e.g. ``/usr/bin/curl``."""
        return _CALLER_PID_SUFFIX.sub("", self.process) if self.process else None


@dataclass
class HttpEvent:
    action: str  # "ALLOWED" or "DENIED"
    method: str  # "GET", "POST", "PUT", etc.
    url: str
    raw: str


@dataclass
class ProcessEvent:
    event_type: str  # "launch" or "terminate"
    binary: str
    pid: int
    command: str | None
    exit_code: int | None
    raw: str


@dataclass
class Process:
    """A launched process, paired with its PROC:TERMINATE event when one was logged."""

    binary: str
    pid: int
    command: str | None
    exit_code: int | None = None


@dataclass
class FindingEvent:
    disposition: str  # "BLOCKED"
    title: str
    raw: str


@dataclass
class OCSFEvents:
    """All OCSF events parsed from a sandbox log window."""

    network_allowed: list[NetworkEvent] = field(default_factory=list)
    network_blocked: list[NetworkEvent] = field(default_factory=list)
    # Closed by a policy generation change rather than denied by policy.
    network_interrupted: list[NetworkEvent] = field(default_factory=list)
    http_allowed: list[HttpEvent] = field(default_factory=list)
    http_blocked: list[HttpEvent] = field(default_factory=list)
    processes: list[Process] = field(default_factory=list)  # in launch order
    findings: list[FindingEvent] = field(default_factory=list)

    @property
    def network_allowed_endpoints(self) -> list[str]:
        return [e.endpoint for e in self.network_allowed]

    @property
    def network_blocked_endpoints(self) -> list[str]:
        return [e.endpoint for e in self.network_blocked]

    @property
    def network_interrupted_endpoints(self) -> list[str]:
        return [e.endpoint for e in self.network_interrupted]

    @property
    def network_callers(self) -> list[str]:
        """Distinct executables that made allowed or denied network connections.

        OpenShell verifies these paths inside the sandbox, so they are the
        trustworthy record of which processes ran and tried to reach the network.
        """
        callers = (e.binary for e in [*self.network_allowed, *self.network_blocked])
        return list(dict.fromkeys(c for c in callers if c))


def _parse_message(msg: str) -> NetworkEvent | HttpEvent | ProcessEvent | FindingEvent | None:
    """Parse a single OCSF shorthand message string into a typed event."""
    m = _NET_PATTERN.search(msg)
    if m:
        action, process, host, port = m.groups()
        return NetworkEvent(
            action=action.upper(),
            process=process,
            host=host,
            port=int(port) if port else None,
            endpoint=f"{host}:{port}" if port else host,
            raw=msg,
        )

    m = _HTTP_PATTERN.search(msg)
    if m:
        _, action, method, url = m.groups()
        return HttpEvent(action=action.upper(), method=method.upper(), url=url, raw=msg)

    m = _PROC_LAUNCH_PATTERN.search(msg)
    if m:
        binary, pid, command = m.groups()
        return ProcessEvent(event_type="launch", binary=binary, pid=int(pid), command=command, exit_code=None, raw=msg)

    m = _PROC_TERMINATE_PATTERN.search(msg)
    if m:
        binary, pid, exit_code = m.groups()
        return ProcessEvent(
            event_type="terminate",
            binary=binary,
            pid=int(pid),
            command=None,
            exit_code=int(exit_code) if exit_code is not None else None,
            raw=msg,
        )

    m = _FINDING_PATTERN.search(msg)
    if m:
        disposition, title = m.groups()
        return FindingEvent(disposition=disposition.upper(), title=title, raw=msg)

    return None


def parse_ocsf_lines(lines: list[str]) -> OCSFEvents:
    """Parse a list of OCSF shorthand message strings into an OCSFEvents aggregate.

    Each PROC:TERMINATE event sets the exit code of the latest launch of its pid,
    so a reused pid is attributed to the right process.
    """
    result = OCSFEvents()
    running: dict[int, Process] = {}
    for msg in lines:
        event = _parse_message(msg)
        if event is None:
            continue
        if isinstance(event, NetworkEvent):
            if event.action == "ALLOWED":
                result.network_allowed.append(event)
            elif _STALE_GENERATION_REASON in msg:
                result.network_interrupted.append(event)
            else:
                result.network_blocked.append(event)
        elif isinstance(event, HttpEvent):
            (result.http_allowed if event.action == "ALLOWED" else result.http_blocked).append(event)
        elif isinstance(event, ProcessEvent):
            if event.event_type == "launch":
                running[event.pid] = Process(binary=event.binary, pid=event.pid, command=event.command)
                result.processes.append(running[event.pid])
            elif (process := running.pop(event.pid, None)) is not None:
                process.exit_code = event.exit_code
        elif isinstance(event, FindingEvent):
            result.findings.append(event)
    return result
