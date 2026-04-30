from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from typing import NamedTuple

import click
import httpx
from agentdojo.benchmark import SuiteResults
from agentdojo.task_suite.task_suite import TaskSuite
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from midojo.agent_client import A2AAgentClient, AgentClient, SimpleHTTPAgentClient
from midojo.attack import create_attack
from midojo.suites import get_suite

console = Console()


class TaskPair(NamedTuple):
    user_task_id: str
    injection_task_id: str


def _utility(value: bool) -> Text:
    return Text("✓ task completed", style="bold green") if value else Text("✗ task not completed", style="bold red")


def _security(value: bool) -> Text:
    if value:
        return Text("💀 attack succeeded", style="bold red")
    return Text("🛡️ attack failed", style="bold green")


async def _fetch_suite_info(control_url: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{control_url}/admin/suite")
        resp.raise_for_status()
        return resp.json()


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


async def run_task(
    control_url: str,
    agent_client: AgentClient,
    user_task_id: str,
    injection_task_id: str | None,
    injections: dict[str, str],
) -> dict:
    async with httpx.AsyncClient(timeout=300.0) as client:
        setup_resp = await client.post(
            f"{control_url}/task/setup",
            json={
                "user_task_id": user_task_id,
                "injection_task_id": injection_task_id,
                "injections": injections,
            },
        )
        setup_resp.raise_for_status()

        prompt_resp = await client.get(f"{control_url}/task/prompt")
        prompt_resp.raise_for_status()
        prompt = prompt_resp.json()["prompt"]

        model_output = await agent_client.send_task(prompt)

        complete_resp = await client.post(
            f"{control_url}/task/complete",
            json={
                "model_output": model_output,
            },
        )
        complete_resp.raise_for_status()

        grade_resp = await client.post(f"{control_url}/task/grade")
        grade_resp.raise_for_status()
        return grade_resp.json()


async def run_benchmark(
    control_url: str,
    agent_client: AgentClient,
    agent_url: str,
    protocol: str,
    suite: TaskSuite,
    suite_name: str,
    attack_name: str | None,
    user_task_ids: list[str] | None,
    injection_task_ids: list[str] | None,
    logdir: Path,
) -> SuiteResults:
    user_tasks_to_run = user_task_ids or list(suite.user_tasks.keys())
    injection_tasks_to_run = injection_task_ids or list(suite.injection_tasks.keys())

    suite_info = await _fetch_suite_info(control_url)
    _print_banner(suite_name, suite_info, attack_name, agent_url, protocol, user_tasks_to_run, injection_tasks_to_run)

    utility_results: dict[TaskPair, bool] = {}
    security_results: dict[TaskPair, bool] = {}

    if attack_name is None:
        for ut_id in user_tasks_to_run:
            console.print(f"  Running [bold]{ut_id}[/bold] ...", end=" ")
            result = await run_task(control_url, agent_client, ut_id, None, {})
            utility_results[TaskPair(ut_id, "")] = result["utility"]
            console.print(_utility(result["utility"]))
    else:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{control_url}/admin/injection-candidates")
            resp.raise_for_status()
            candidates = resp.json()
        attack = create_attack(attack_name, suite, candidates)
        for ut_id in user_tasks_to_run:
            user_task = suite.user_tasks[ut_id]
            injectable = len(candidates.get(ut_id, [])) > 0
            for it_id in injection_tasks_to_run:
                injection_task = suite.injection_tasks[it_id]
                if not injectable:
                    console.print(f"  Running [bold]{ut_id}[/bold] x [bold]{it_id}[/bold] ...", end=" ")
                    result = await run_task(control_url, agent_client, ut_id, None, {})
                    utility_results[TaskPair(ut_id, it_id)] = result["utility"]
                    console.print(_utility(result["utility"]), " | ", Text("N/A (not injectable)", style="dim"))
                else:
                    console.print(f"  Running [bold]{ut_id}[/bold] x [bold]{it_id}[/bold] ...", end=" ")
                    injections = attack.attack(user_task, injection_task)
                    result = await run_task(control_url, agent_client, ut_id, it_id, injections)
                    utility_results[TaskPair(ut_id, it_id)] = result["utility"]
                    security_results[TaskPair(ut_id, it_id)] = result["security"]
                    console.print(_utility(result["utility"]), " | ", _security(result["security"]))

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
@click.option("--protocol", type=click.Choice(["http", "a2a"]), required=True, help="Agent communication protocol.")
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
) -> None:
    for module in modules_to_load:
        importlib.import_module(module)

    suite_module = get_suite(suite_name)
    suite = suite_module.task_suite
    agent_client: AgentClient
    if protocol == "a2a":
        agent_client = A2AAgentClient(agent_url)
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
        )
    )


if __name__ == "__main__":
    main()
