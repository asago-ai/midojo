from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import os
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, NamedTuple

import click
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from midojo.agent_client import (
    A2AAgentClient,
    AgentClient,
    OGXResponsesClient,
    OpenAIResponsesAgentClient,
    OpenShellAgentClient,
    PIAgentClient,
    SimpleHTTPAgentClient,
)
from midojo.attacks import Attacker, AttemptOutcome, StaticAttacker
from midojo.control_plane.client import ControlPlaneClient
from midojo.control_plane.config import CONTROL_TOKEN_ENV
from midojo.control_plane.models import GradeResponse
from midojo.runtimes import AgentRuntime
from midojo.runtimes.openshell import OpenShellRuntime
from midojo.suites import get_suite, list_suites
from midojo.yaml_task_suite import YAMLTaskSuite

console = Console()


def _resolve_system_message(suite_name: str) -> str:
    module_path = suite_name if "." in suite_name else f"suites.{suite_name}"
    try:
        mod = importlib.import_module(module_path)
    except ImportError:
        mod = None
    msg = getattr(mod, "SYSTEM_MESSAGE", None)
    if not msg:
        console.print(f"[dim]No SYSTEM_MESSAGE in '{suite_name}' — running without a system prompt.[/dim]")
        return ""
    return msg


class TaskPair(NamedTuple):
    user_task_id: str
    injection_task_id: str


class TaskResult(NamedTuple):
    eval_id: str
    prompt: str
    agent_output: str
    grade: GradeResponse


def _utility(value: bool) -> Text:
    return Text("✅ task completed", style="bold green") if value else Text("❌ task not completed", style="bold red")


def _print_agent_text(label: str, text: str, max_len: int = 200) -> None:
    text = (text or "").replace("\n", " ").strip()
    if len(text) > max_len:
        text = text[:max_len] + "…"
    line = Text(f"    {label}: ", style="dim")
    line.append(text, style="italic")
    console.print(line)


def _security(value: bool) -> Text:
    if value:
        return Text("💀 attack succeeded", style="bold red")
    return Text("🛡️ attack failed", style="bold green")


def _print_banner(
    suite_name: str,
    agent_uri: str,
    protocol: str,
    user_tasks_to_run: list[str],
    injection_tasks_to_run: list[str],
) -> None:
    lines = Text()
    lines.append("Suite       ", style="dim")
    lines.append(f"{suite_name}\n")
    lines.append("Agent       ", style="dim")
    lines.append(f"{agent_uri} ({protocol})\n")
    lines.append("Tasks       ", style="dim")
    if injection_tasks_to_run:
        lines.append(f"{len(user_tasks_to_run)} user x {len(injection_tasks_to_run)} injection\n")
    else:
        lines.append(f"{len(user_tasks_to_run)} user (no injections)\n")
    console.print(Panel(lines, title="midojo orchestrator", border_style="cyan", padding=(1, 2)))
    console.print()


def _with_count(cell: Text, count: int, total: int, attempts: int, note: str = "") -> Text:
    """Append a ``(count/total)`` attempt tally to a verdict cell when K>1.

    The tally sits inline instead of in a separate column, and never changes the
    verdict beside it.
    """
    if attempts > 1:
        cell.append(f"  ({count}/{total}{note})", style="dim")
    return cell


def _utility_cell(util: bool, outcomes: list[AttemptOutcome], attempts: int) -> Text:
    """The Utility verdict (task completed on every attempt), tallying the attempts that completed it."""
    return _with_count(_utility(util), sum(1 for o in outcomes if o.utility), len(outcomes), attempts)


def _security_cell(sec: bool | None, outcomes: list[AttemptOutcome], attempts: int) -> Text:
    """The Security verdict (attack succeeded on any attempt), or N/A when no attempt delivered the payload.

    The tally counts only attempts that delivered the payload, as the Security
    percentage leaves out N/A pairs; undelivered attempts are noted as N/A.
    """
    if sec is None:
        return Text("N/A", style="dim")
    delivered = sum(1 for o in outcomes if o.delivered)
    undelivered = len(outcomes) - delivered
    note = f", {undelivered} N/A" if undelivered else ""
    return _with_count(_security(sec), sum(1 for o in outcomes if o.broke), delivered, attempts, note)


def _print_results_table(
    utility_results: dict[TaskPair, bool],
    security_results: dict[TaskPair, bool],
    has_injections: bool,
    results_file: Path,
    attempt_log: dict[TaskPair, list[AttemptOutcome]] | None = None,
    attempts: int = 1,
) -> None:
    attempt_log = attempt_log or {}
    table = Table(title="Results", border_style="cyan", show_lines=True)
    table.add_column("User Task", style="bold")
    if has_injections:
        table.add_column("Injection Task")
    table.add_column("Utility", justify="center")
    if has_injections:
        table.add_column("Security", justify="center")

    for pair, util in utility_results.items():
        outcomes = attempt_log.get(pair, [])
        util_cell = _utility_cell(util, outcomes, attempts)
        if has_injections:
            sec_cell = _security_cell(security_results.get(pair), outcomes, attempts)
            table.add_row(pair.user_task_id, pair.injection_task_id, util_cell, sec_cell)
        else:
            table.add_row(pair.user_task_id, util_cell)

    table.add_section()
    if utility_results:
        util_avg = f"{sum(utility_results.values()) / len(utility_results) * 100:.1f}%"
    else:
        util_avg = "-"
    if security_results:
        sec_avg = f"{sum(security_results.values()) / len(security_results) * 100:.1f}%"
    else:
        sec_avg = "-"

    if has_injections:
        table.add_row("", "", Text(util_avg, style="bold"), Text(sec_avg, style="bold"))
    else:
        table.add_row("", Text(util_avg, style="bold"))

    console.print(table)
    console.print(f"\nResults saved to [cyan]{results_file}[/cyan]")


async def _injection_reached_agent(
    control: ControlPlaneClient, run_id: str, eval_id: str, injections: dict[str, str]
) -> list[str]:
    """Return channels through which an injection payload reached the agent.

    Checks both the agent input (prompt) and function call results (tool output).
    """
    evaluation = await control.evaluation(run_id, eval_id)
    payloads = [v for v in injections.values() if v]
    if not payloads:
        return []

    def _normalize(text: str) -> str:
        return " ".join(text.split()).lower()

    normalized_payloads = [_normalize(p) for p in payloads]
    hits: list[str] = []
    agent_input = evaluation.agent_input or ""
    if agent_input and any(p in _normalize(agent_input) for p in normalized_payloads):
        hits.append("agent input")
    for call in evaluation.function_calls:
        result = _normalize(call.result)
        if any(p in result for p in normalized_payloads):
            hits.append(call.function)
    return hits


async def run_task(
    control: ControlPlaneClient,
    agent_client: AgentClient,
    run_id: str,
    user_task_id: str,
    injection_task_id: str | None,
    injections: dict[str, str],
    *,
    runtime: AgentRuntime,
) -> TaskResult:
    """Run a single evaluation, with the runtime set up around the agent's execution."""
    evaluation = await control.create_evaluation(run_id, user_task_id, injection_task_id, injections)
    eval_id, prompt, session_token = evaluation.id, evaluation.prompt, evaluation.session_token
    pair = f"{user_task_id} x {injection_task_id}" if injection_task_id else user_task_id

    try:
        try:
            with console.status(f"[dim]{pair} · setting up the {runtime.name} runtime…[/dim]", spinner="dots"):
                await asyncio.to_thread(
                    runtime.setup,
                    injections,
                    session_token=session_token,
                    eval_id=eval_id,
                    user_task_id=user_task_id,
                    injection_task_id=injection_task_id,
                )
            with console.status(f"[dim]{pair} · running the agent…[/dim]", spinner="dots"):
                agent_output = await agent_client.send_task(prompt, session_token=session_token)
            with console.status(f"[dim]{pair} · collecting runtime observations…[/dim]", spinner="dots"):
                observations = await asyncio.to_thread(runtime.observe)
            for source, observed in observations.items():
                await control.record_observations(run_id, eval_id, source, observed)
        finally:
            with console.status(f"[dim]{pair} · tearing down the {runtime.name} runtime…[/dim]", spinner="dots"):
                await asyncio.to_thread(runtime.teardown)

        await control.complete_evaluation(run_id, eval_id, agent_output)
        grade = await control.grade_evaluation(run_id, eval_id)
        return TaskResult(eval_id=eval_id, prompt=prompt, agent_output=agent_output, grade=grade)
    except BaseException:
        with contextlib.suppress(httpx.HTTPError):
            await control.revoke_session(run_id, eval_id)
        raise


def _print_attempt(
    control_url: str,
    run_id: str,
    ut_id: str,
    it_id: str | None,
    prompt: str,
    outcome: AttemptOutcome,
    attempts: int,
) -> None:
    eval_url = f"{control_url}/runs/{run_id}/evaluations/{outcome.eval_id}"
    label = f"[bold]{ut_id}[/bold] x [bold]{it_id}[/bold]" if it_id else f"[bold]{ut_id}[/bold]"
    if attempts > 1:
        label = f"[magenta]attempt {outcome.attempt}/{attempts}[/magenta] {label}"
    console.print(f"  [dim]\\[eval: [link={eval_url}][cyan]{outcome.eval_id}[/cyan][/link]][/dim] {label}")
    _print_agent_text("agent input", prompt)
    _print_agent_text("agent output", outcome.agent_output)
    console.print("    ", _utility(outcome.utility))
    if it_id:
        if outcome.delivered:
            counts = Counter(outcome.delivered_where)
            parts = [f"{ch} x{n}" if n > 1 else ch for ch, n in counts.items()]
            detail = f"injection in {', '.join(parts)}"
            if outcome.broke and outcome.security_reason:
                # attack succeeded — name the criterion that graded it
                detail += f" · {outcome.security_reason}"
            console.print("    ", _security(outcome.broke), Text(f"  ({detail})", style="dim"))
        else:
            console.print("    ", Text("N/A (payload not in any result)", style="dim"))


def _attempt_metrics(outcomes: list[AttemptOutcome]) -> dict[str, Any]:
    """Aggregate per-attempt outcomes into the metrics recorded for a pair.

    The overall attack success rate is the Security column (share of pairs that
    broke), so this deliberately records raw counts — not a per-pair rate that
    would read as a second, competing ASR.
    """
    return {
        "attempts_run": len(outcomes),
        "completed": sum(1 for o in outcomes if o.utility),
        "delivered": sum(1 for o in outcomes if o.delivered),
        "successes": sum(1 for o in outcomes if o.broke),
        "attempts_to_break": next((o.attempt for o in outcomes if o.broke), None),
    }


async def _run_pair_attempts(
    control: ControlPlaneClient,
    control_url: str,
    agent_client: AgentClient,
    run_id: str,
    ut_id: str,
    it_id: str | None,
    attacker: Attacker,
    attempts: int,
    *,
    runtime: AgentRuntime,
) -> list[AttemptOutcome]:
    """Run one (user_task x injection_task) pair ``attempts`` times.

    Every attempt is a new evaluation with its own session and a freshly
    provisioned environment. With the ``openshell`` runtime it also runs in a
    fresh sandbox; an ``unmanaged`` agent is reused across attempts, as it is
    across pairs, so state the agent keeps between tasks can carry over. The
    attacker proposes each attempt's injection given the outcomes of the earlier
    ones. Every attempt runs: the static attacker's point at K>1 is to see all of
    them, and stopping at the first break is left to an attacker that hunts for
    one.
    """
    outcomes: list[AttemptOutcome] = []
    for k in range(1, attempts + 1):
        # No objective source exists yet; an attacker that pursues a goal defines one.
        attempt = await attacker.propose(None, outcomes)
        injections = attempt.injections
        result = await run_task(control, agent_client, run_id, ut_id, it_id, injections, runtime=runtime)
        grade = result.grade
        hit = await _injection_reached_agent(control, run_id, result.eval_id, injections) if it_id else []
        broke = bool(it_id) and grade.security and bool(hit)
        outcome = AttemptOutcome(
            attempt=k,
            injections=injections,
            delivered=bool(hit),
            delivered_where=hit,
            broke=broke,
            security_reason=grade.security_reason if broke else None,
            utility=grade.utility,
            agent_output=result.agent_output,
            eval_id=result.eval_id,
        )
        outcomes.append(outcome)
        _print_attempt(control_url, run_id, ut_id, it_id, result.prompt, outcome, attempts)
    return outcomes


async def _run_benchmark(
    control: ControlPlaneClient,
    control_url: str,
    agent_client: AgentClient,
    agent_uri: str,
    protocol: str,
    suite: YAMLTaskSuite,
    suite_name: str,
    user_task_ids: list[str] | None,
    injection_task_ids: list[str] | None,
    logdir: Path,
    attempts: int = 1,
) -> None:
    runtime = suite.runtime
    user_tasks_to_run = user_task_ids or list(suite.user_tasks.keys())
    injection_tasks_to_run: list[str]
    if injection_task_ids is not None:
        injection_tasks_to_run = injection_task_ids
    elif user_task_ids is None:
        injection_tasks_to_run = list(suite.injection_tasks.keys())
    else:
        # -ut without -it: utility-only run
        injection_tasks_to_run = []

    run_id = (await control.create_run(suite_name)).id
    _print_banner(suite_name, agent_uri, protocol, user_tasks_to_run, injection_tasks_to_run)
    console.print(f"  [dim]run[/dim] [cyan underline]{run_id}[/cyan underline]\n")

    utility_results: dict[TaskPair, bool] = {}
    security_results: dict[TaskPair, bool] = {}
    security_reasons: dict[TaskPair, str | None] = {}
    attempt_log: dict[TaskPair, list[AttemptOutcome]] = {}

    it_ids_to_run: list[str | None] = [*injection_tasks_to_run] if injection_tasks_to_run else [None]
    started: str | None = None
    try:
        with console.status(f"[dim]starting the {runtime.name} runtime…[/dim]", spinner="dots"):
            started = await asyncio.to_thread(runtime.start_run, run_id, suite_name=suite_name)
        if started:
            console.print(f"  [magenta]{runtime.name}[/magenta] [dim]{started}[/dim] [green]ready[/green]\n")

        for ut_id in user_tasks_to_run:
            for it_id in it_ids_to_run:
                attacker: Attacker = StaticAttacker(suite.get_probes_for_task(it_id) if it_id else {})
                outcomes = await _run_pair_attempts(
                    control,
                    control_url,
                    agent_client,
                    run_id,
                    ut_id,
                    it_id,
                    attacker,
                    attempts,
                    runtime=runtime,
                )
                pair = TaskPair(ut_id, it_id or "")
                attempt_log[pair] = outcomes
                # Across K attempts each verdict is the agent's worst case, independent
                # of attempt order: Utility holds only if every attempt completed the
                # task; Security fails if any attempt broke the agent. A pair is N/A
                # when no attempt delivered the payload. With K=1 both reduce to the
                # single attempt's result.
                utility_results[pair] = all(o.utility for o in outcomes)
                if it_id and any(o.delivered for o in outcomes):
                    first_break = next((o for o in outcomes if o.broke), None)
                    security_results[pair] = first_break is not None
                    security_reasons[pair] = first_break.security_reason if first_break else None
    finally:
        with console.status(f"[dim]stopping the {runtime.name} runtime…[/dim]", spinner="dots"):
            await asyncio.to_thread(runtime.end_run)
        if started:
            console.print(f"\n  [magenta]{runtime.name}[/magenta] [dim]{started}[/dim] [green]cleaned up[/green]")

    console.print()

    logdir.mkdir(parents=True, exist_ok=True)
    results_file = logdir / "results.json"
    all_security = {f"{k.user_task_id},{k.injection_task_id}": security_results.get(k) for k in utility_results}
    all_security_reason = {f"{k.user_task_id},{k.injection_task_id}": security_reasons.get(k) for k in utility_results}
    results: dict[str, Any] = {
        "run_id": run_id,
        "suite_name": suite_name,
        "utility": {f"{k.user_task_id},{k.injection_task_id}": v for k, v in utility_results.items()},
        "security": all_security,
        "security_reason": all_security_reason,
    }
    # The attempts dimension is additive: a default (single-attempt) run writes
    # exactly the historical shape, so existing result consumers are unaffected.
    if attempts > 1:
        results["attempts"] = attempts
        results["metrics"] = {
            f"{k.user_task_id},{k.injection_task_id}": _attempt_metrics(attempt_log[k]) for k in utility_results
        }
        results["attempt_log"] = {
            f"{k.user_task_id},{k.injection_task_id}": [asdict(o) for o in attempt_log[k]] for k in utility_results
        }
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    _print_results_table(
        utility_results, security_results, bool(injection_tasks_to_run), results_file, attempt_log, attempts
    )


async def run_benchmark(
    control_url: str,
    agent_client: AgentClient,
    agent_uri: str,
    protocol: str,
    suite: YAMLTaskSuite,
    suite_name: str,
    user_task_ids: list[str] | None,
    injection_task_ids: list[str] | None,
    logdir: Path,
    attempts: int = 1,
    control_token: str | None = None,
    http: httpx.AsyncClient | None = None,
) -> None:
    """Run the benchmark against the control plane at ``control_url``.

    ``http`` is the client for control-plane requests; by default the control
    plane client opens its own.
    """
    async with ControlPlaneClient(control_url, token=control_token, http=http) as control:
        await _run_benchmark(
            control,
            control_url,
            agent_client,
            agent_uri,
            protocol,
            suite,
            suite_name,
            user_task_ids,
            injection_task_ids,
            logdir,
            attempts,
        )


@click.command()
@click.option(
    "--control-url",
    default="http://localhost:8080",
    help="URL of the control plane started with midojo-serve. "
    "OpenShell sandboxes get this URL too, with localhost rewritten to reach the host.",
)
@click.option(
    "--control-token",
    envvar=CONTROL_TOKEN_ENV,
    default=None,
    help=f"Control token the control plane was started with. Never passed to the agent; env: {CONTROL_TOKEN_ENV}.",
)
@click.option(
    "--gateway",
    default=None,
    help="OpenShell gateway to run the agent's sandboxes on. Required for suites with the openshell agent_runtime.",
)
@click.option(
    "--agent-uri",
    default=None,
    help="Where to reach an unmanaged agent. A URL for http/a2a/ogx/openai; a local path to the agent dir for pi.",
)
@click.option(
    "--suite", "suite_name", required=True, help=f"Benchmark suite name. Built-in: {', '.join(list_suites())}."
)
@click.option("--user-task", "-ut", "user_tasks", multiple=True, default=(), help="Specific user task IDs.")
@click.option(
    "--injection-task", "-it", "injection_tasks", multiple=True, default=(), help="Specific injection task IDs."
)
@click.option("--logdir", default="./runs", type=Path, help="Directory to store results.")
@click.option(
    "--module-to-load", "-ml", "modules_to_load", multiple=True, default=(), help="Additional modules to import."
)
@click.option(
    "--protocol",
    type=click.Choice(["http", "a2a", "pi", "ogx", "openai"]),
    default=None,
    help="How to talk to an unmanaged agent. "
    "API keys are read from env vars: OPENAI_API_KEY (openai), OGX_CLIENT_API_KEY (ogx).",
)
@click.option(
    "--ogx-shield", default=None, envvar="OGX_SHIELD_ID", help="Shield ID for OGX guardrails (ogx protocol only)."
)
@click.option(
    "--mcp-server-url",
    envvar="MCP_SERVER_URL",
    help="MCP server URL reachable by the inference server. Required for ogx/openai; env: MCP_SERVER_URL.",
)
@click.option(
    "--mcp-server-label",
    default=None,
    envvar="MCP_SERVER_LABEL",
    help="Label the MCP server is registered under on the agent's inference server. "
    "Defaults to the suite name. Override when the server expects a different label.",
)
@click.option(
    "--model-name",
    default=None,
    envvar="MODEL_NAME",
    help="Model ID. Required for ogx/openai; env: MODEL_NAME.",
)
@click.option(
    "--attempts",
    "-k",
    default=1,
    type=click.IntRange(min=1),
    help="Run each user x injection pair this many times (default 1, single-shot as before). "
    "Each attempt is a new evaluation, in a fresh sandbox with the openshell runtime; an "
    "unmanaged agent is reused across attempts, so state it keeps can carry over. With >1, "
    "Utility holds only if every attempt completed the task, Security fails if any attempt "
    "broke the agent, and each cell shows its attempt tally.",
)
def main(
    control_url: str,
    control_token: str | None,
    gateway: str | None,
    agent_uri: str | None,
    suite_name: str,
    user_tasks: tuple[str, ...],
    injection_tasks: tuple[str, ...],
    logdir: Path,
    modules_to_load: tuple[str, ...],
    protocol: str | None,
    ogx_shield: str | None,
    mcp_server_url: str | None,
    mcp_server_label: str | None,
    model_name: str | None,
    attempts: int,
) -> None:
    for module in modules_to_load:
        importlib.import_module(module)

    suite = get_suite(suite_name)
    agent_client: AgentClient

    if isinstance(suite.runtime, OpenShellRuntime):
        if agent_uri or protocol:
            raise click.UsageError(
                f"Suite {suite_name!r} runs its agent in OpenShell; pass --gateway instead of --agent-uri/--protocol."
            )
        if not gateway:
            raise click.UsageError(f"Suite {suite_name!r} runs its agent in OpenShell and requires --gateway.")
        suite.runtime.configure(cluster=gateway, control_url=control_url)
        agent_client = OpenShellAgentClient(suite.runtime)
        agent_uri, protocol = gateway, "openshell"
    elif gateway:
        raise click.UsageError(
            f"--gateway applies only to suites with the openshell agent_runtime; {suite_name!r} is {suite.runtime.name}."
        )
    elif not agent_uri or not protocol:
        raise click.UsageError(f"Suite {suite_name!r} has an unmanaged agent and requires --agent-uri and --protocol.")
    elif protocol == "a2a":
        agent_client = A2AAgentClient(agent_uri)
    elif protocol == "pi":
        agent_client = PIAgentClient(agent_uri, control_url)
    elif protocol in {"ogx", "openai"}:
        if not model_name:
            raise click.UsageError(f"--protocol {protocol} requires --model-name or MODEL_NAME.")
        if not mcp_server_url:
            raise click.UsageError(f"--protocol {protocol} requires --mcp-server-url or MCP_SERVER_URL.")
        system_message = _resolve_system_message(suite_name)
        if protocol == "ogx":
            agent_client = OGXResponsesClient(
                ogx_url=agent_uri,
                model=model_name,
                mcp_server_url=mcp_server_url,
                mcp_server_label=mcp_server_label or suite_name,
                instructions=system_message,
                shield_id=ogx_shield,
            )
        else:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise click.UsageError("--protocol openai requires OPENAI_API_KEY.")
            agent_client = OpenAIResponsesAgentClient(
                base_url=agent_uri,
                model=model_name,
                mcp_server_url=mcp_server_url,
                mcp_server_label=mcp_server_label or suite_name,
                api_key=api_key,
                instructions=system_message,
            )
    else:
        agent_client = SimpleHTTPAgentClient(agent_uri)

    asyncio.run(
        run_benchmark(
            control_url=control_url,
            agent_client=agent_client,
            agent_uri=agent_uri,
            protocol=protocol,
            suite=suite,
            suite_name=suite_name,
            user_task_ids=list(user_tasks) if user_tasks else None,
            injection_task_ids=list(injection_tasks) if injection_tasks else None,
            logdir=logdir,
            attempts=attempts,
            control_token=control_token or None,
        )
    )


if __name__ == "__main__":
    main()
