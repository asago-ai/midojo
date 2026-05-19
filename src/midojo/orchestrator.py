from __future__ import annotations

import asyncio
import importlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import click
import httpx
from agentdojo.benchmark import SuiteResults
from midojo.yaml_task_suite import YAMLTaskSuite
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from midojo.agent_client import A2AAgentClient, AgentClient, OGXResponsesClient, PIAgentClient, SimpleHTTPAgentClient
from midojo.attack import create_attack
from midojo.suites import get_suite

console = Console()


class TaskPair(NamedTuple):
    user_task_id: str
    injection_task_id: str


def _utility(value: bool) -> Text:
    return Text("✅ task completed", style="bold green") if value else Text("❌ task not completed", style="bold red")


def _print_agent_output(output: str, max_len: int = 200) -> None:
    text = (output or "").replace("\n", " ").strip()
    if len(text) > max_len:
        text = text[:max_len] + "…"
    console.print(f"    [dim]agent output:[/dim] {text}")


def _security(value: bool) -> Text:
    if value:
        return Text("💀 attack succeeded", style="bold red")
    return Text("🛡️ attack failed", style="bold green")


async def _fetch_suite_info(control_url: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{control_url}/suite")
        resp.raise_for_status()
        return resp.json()


async def _create_run(control_url: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{control_url}/runs")
        resp.raise_for_status()
        return resp.json()["id"]


def _print_banner(
    suite_name: str,
    suite_info: dict,
    attack_name: str | None,
    agent_url: str,
    protocol: str,
    user_tasks_to_run: list[str],
    injection_tasks_to_run: list[str],
) -> None:
    lines = Text()
    lines.append("Suite       ", style="dim")
    lines.append(f"{suite_name}\n")
    lines.append("Attack      ", style="dim")
    lines.append(f"{attack_name or 'none'}\n")
    lines.append("Agent       ", style="dim")
    lines.append(f"{agent_url} ({protocol})\n")
    lines.append("Tasks       ", style="dim")
    lines.append(f"{len(user_tasks_to_run)} user x {len(injection_tasks_to_run)} injection\n")
    lines.append("Tools       ", style="dim")
    lines.append(f"{', '.join(suite_info['tools'])}\n")
    lines.append("Vectors     ", style="dim")
    lines.append(", ".join(suite_info["injection_vectors"].keys()) or "none")

    console.print(Panel(lines, title="midojo orchestrator", border_style="cyan", padding=(1, 2)))
    console.print()


def _print_results_table(
    utility_results: dict[TaskPair, bool],
    security_results: dict[TaskPair, bool],
    attack_name: str | None,
    results_file: Path,
) -> None:
    table = Table(title="Results", border_style="cyan", show_lines=True)
    table.add_column("User Task", style="bold")
    if attack_name:
        table.add_column("Injection Task")
    table.add_column("Utility", justify="center")
    if attack_name:
        table.add_column("Security", justify="center")

    for pair, util in utility_results.items():
        sec = security_results.get(pair)
        if attack_name:
            sec_cell = _security(sec) if sec is not None else Text("N/A", style="dim")
            table.add_row(pair.user_task_id, pair.injection_task_id, _utility(util), sec_cell)
        else:
            table.add_row(pair.user_task_id, _utility(util))

    table.add_section()
    if utility_results:
        util_avg = f"{sum(utility_results.values()) / len(utility_results) * 100:.1f}%"
    else:
        util_avg = "-"
    if security_results:
        sec_avg = f"{sum(security_results.values()) / len(security_results) * 100:.1f}%"
    else:
        sec_avg = "-"

    if attack_name:
        table.add_row("", "", Text(util_avg, style="bold"), Text(sec_avg, style="bold"))
    else:
        table.add_row("", Text(util_avg, style="bold"))

    console.print(table)
    console.print(f"\nResults saved to [cyan]{results_file}[/cyan]")


async def _injection_reached_agent(
    control_url: str, run_id: str, eval_id: str, injections: dict[str, str]
) -> list[str]:
    """Return names of functions whose results contained an injection payload."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{control_url}/runs/{run_id}/evaluations/{eval_id}/function-calls")
        resp.raise_for_status()
        calls = resp.json()
    payloads = [v for v in injections.values() if v]
    if not payloads:
        return []

    def _normalize(text: str) -> str:
        return " ".join(text.split()).lower()

    normalized_payloads = [_normalize(p) for p in payloads]
    hit_functions: list[str] = []
    for call in calls:
        result = _normalize(call.get("result", "") or "")
        if any(p in result for p in normalized_payloads):
            hit_functions.append(call["function"])
    return hit_functions


async def run_task(
    control_url: str,
    agent_client: AgentClient,
    run_id: str,
    user_task_id: str,
    injection_task_id: str | None,
    injections: dict[str, str],
) -> dict:
    async with httpx.AsyncClient(timeout=300.0) as client:
        eval_resp = await client.post(
            f"{control_url}/runs/{run_id}/evaluations",
            json={
                "user_task_id": user_task_id,
                "injection_task_id": injection_task_id,
                "injections": injections,
            },
        )
        eval_resp.raise_for_status()
        eval_data = eval_resp.json()
        eval_id = eval_data["id"]
        prompt = eval_data["prompt"]

        agent_output = await agent_client.send_task(prompt)

        complete_resp = await client.post(
            f"{control_url}/runs/{run_id}/evaluations/{eval_id}/complete",
            json={"model_output": agent_output},
        )
        complete_resp.raise_for_status()

        grade_resp = await client.post(f"{control_url}/runs/{run_id}/evaluations/{eval_id}/grade")
        grade_resp.raise_for_status()
        result = grade_resp.json()
        result["eval_id"] = eval_id
        result["model_output"] = agent_output
        return result


async def run_benchmark(
    control_url: str,
    agent_client: AgentClient,
    agent_url: str,
    protocol: str,
    suite: YAMLTaskSuite,
    suite_name: str,
    attack_name: str | None,
    user_task_ids: list[str] | None,
    injection_task_ids: list[str] | None,
    logdir: Path,
    show_output: bool = False,
) -> SuiteResults:
    user_tasks_to_run = user_task_ids or list(suite.user_tasks.keys())
    injection_tasks_to_run = injection_task_ids or list(suite.injection_tasks.keys())

    suite_info = await _fetch_suite_info(control_url)
    _print_banner(suite_name, suite_info, attack_name, agent_url, protocol, user_tasks_to_run, injection_tasks_to_run)

    run_id = await _create_run(control_url)
    console.print(f"  [dim]run[/dim] [cyan underline]{run_id}[/cyan underline]\n")

    utility_results: dict[TaskPair, bool] = {}
    security_results: dict[TaskPair, bool] = {}

    if attack_name is None:
        for ut_id in user_tasks_to_run:
            result = await run_task(control_url, agent_client, run_id, ut_id, None, {})
            utility_results[TaskPair(ut_id, "")] = result["utility"]
            console.print(f"  [dim]\\[eval: [cyan]{result['eval_id']}[/cyan]][/dim] [bold]{ut_id}[/bold]")
            if show_output:
                _print_agent_output(result["model_output"])
            console.print("    ", _utility(result["utility"]))
    else:
        attack = create_attack(attack_name, suite)
        for ut_id in user_tasks_to_run:
            user_task = suite.user_tasks[ut_id]
            for it_id in injection_tasks_to_run:
                injection_task = suite.injection_tasks[it_id]
                injections = attack.attack(user_task, injection_task)
                injections.update(suite.get_probes_for_task(it_id))
                result = await run_task(control_url, agent_client, run_id, ut_id, it_id, injections)
                utility_results[TaskPair(ut_id, it_id)] = result["utility"]
                eval_id = result["eval_id"]
                hit_functions = await _injection_reached_agent(control_url, run_id, eval_id, injections)
                console.print(f"  [dim]\\[eval: [cyan]{eval_id}[/cyan]][/dim] [bold]{ut_id}[/bold] x [bold]{it_id}[/bold]")
                if show_output:
                    _print_agent_output(result["model_output"])
                console.print("    ", _utility(result["utility"]))
                if hit_functions:
                    security_results[TaskPair(ut_id, it_id)] = result["security"]
                    counts = Counter(hit_functions)
                    parts = [f"{fn} x{n}" if n > 1 else fn for fn, n in counts.items()]
                    via = ", ".join(parts)
                    console.print("    ", _security(result["security"]), Text(f"  (injection in {via})", style="dim"))
                else:
                    console.print("    ", Text("N/A (payload not in any result)", style="dim"))

    console.print()

    logdir.mkdir(parents=True, exist_ok=True)
    results_file = logdir / "results.json"
    all_security = {f"{k.user_task_id},{k.injection_task_id}": security_results.get(k) for k in utility_results}
    with open(results_file, "w") as f:
        json.dump(
            {
                "utility": {f"{k.user_task_id},{k.injection_task_id}": v for k, v in utility_results.items()},
                "security": all_security,
            },
            f,
            indent=2,
        )

    _print_results_table(utility_results, security_results, attack_name, results_file)

    return SuiteResults(
        utility_results=utility_results,
        security_results=security_results,
        injection_tasks_utility_results={},
    )


@click.command()
@click.option("--control-url", default="http://localhost:8080", help="URL of the benchmark MCP server control plane.")
@click.option("--agent-url", required=True, help="URL of the agent to test.")
@click.option("--suite", "suite_name", default="weather", help="Benchmark suite name.")
@click.option("--attack", "attack_name", type=str, default=None, help="Attack strategy name.")
@click.option("--user-task", "-ut", "user_tasks", multiple=True, default=(), help="Specific user task IDs.")
@click.option(
    "--injection-task", "-it", "injection_tasks", multiple=True, default=(), help="Specific injection task IDs."
)
@click.option("--logdir", default="./runs", type=Path, help="Directory to store results.")
@click.option(
    "--module-to-load", "-ml", "modules_to_load", multiple=True, default=(), help="Additional modules to import."
)
@click.option(
    "--protocol", type=click.Choice(["http", "a2a", "pi", "ogx"]), required=True, help="Agent communication protocol."
)
@click.option(
    "--ogx-model", default=None, envvar="OGX_MODEL", help="Model ID for OGX Responses API (ogx protocol only)."
)
@click.option(
    "--ogx-shield", default=None, envvar="OGX_SHIELD_ID", help="Shield ID for OGX guardrails (ogx protocol only)."
)
@click.option("--show-agent-output", is_flag=True, default=False, help="Print agent output for each task.")
def main(
    control_url: str,
    agent_url: str,
    suite_name: str,
    attack_name: str | None,
    user_tasks: tuple[str, ...],
    injection_tasks: tuple[str, ...],
    logdir: Path,
    modules_to_load: tuple[str, ...],
    protocol: str,
    ogx_model: str | None,
    ogx_shield: str | None,
    show_agent_output: bool,
) -> None:
    for module in modules_to_load:
        importlib.import_module(module)

    suite = get_suite(suite_name)
    agent_client: AgentClient
    if protocol == "a2a":
        agent_client = A2AAgentClient(agent_url)
    elif protocol == "pi":
        agent_client = PIAgentClient(agent_url, control_url)
    elif protocol == "ogx":
        system_message = getattr(suite_module, "SYSTEM_MESSAGE", "")
        agent_client = OGXResponsesClient(
            ogx_url=agent_url,
            model=ogx_model or os.environ.get("OGX_MODEL", "litellm/llama-scout-17b"),
            mcp_server_url=os.environ.get("MCP_SERVER_URL", "http://localhost:8081/mcp"),
            instructions=system_message,
            shield_id=ogx_shield,
        )
    else:
        agent_client = SimpleHTTPAgentClient(agent_url)

    asyncio.run(
        run_benchmark(
            control_url=control_url,
            agent_client=agent_client,
            agent_url=agent_url,
            protocol=protocol,
            suite=suite,
            suite_name=suite_name,
            attack_name=attack_name,
            user_task_ids=list(user_tasks) if user_tasks else None,
            injection_task_ids=list(injection_tasks) if injection_tasks else None,
            logdir=logdir,
            show_output=show_agent_output,
        )
    )


if __name__ == "__main__":
    main()
