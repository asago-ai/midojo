from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import click
import httpx
from agentdojo.attacks.attack_registry import load_attack
from agentdojo.benchmark import SuiteResults
from agentdojo.task_suite.task_suite import TaskSuite

from midojo.agent_client import A2AAgentClient, AgentClient, SimpleHTTPAgentClient
from midojo.suites import get_suite


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
    suite: TaskSuite,
    attack_name: str | None,
    user_task_ids: list[str] | None,
    injection_task_ids: list[str] | None,
    logdir: Path,
) -> SuiteResults:
    user_tasks_to_run = user_task_ids or list(suite.user_tasks.keys())
    injection_tasks_to_run = injection_task_ids or list(suite.injection_tasks.keys())

    utility_results: dict[tuple[str, str], bool] = {}
    security_results: dict[tuple[str, str], bool] = {}

    if attack_name is None:
        for ut_id in user_tasks_to_run:
            click.echo(f"Running {ut_id} (no attack)...")
            result = await run_task(control_url, agent_client, ut_id, None, {})
            utility_results[(ut_id, "")] = result["utility"]
            click.echo(f"  utility={result['utility']}")
    else:
        attack = load_attack(attack_name, suite, None)  # type: ignore
        for ut_id in user_tasks_to_run:
            user_task = suite.user_tasks[ut_id]
            for it_id in injection_tasks_to_run:
                injection_task = suite.injection_tasks[it_id]
                click.echo(f"Running {ut_id} x {it_id} (attack={attack_name})...")
                injections = attack.attack(user_task, injection_task)
                result = await run_task(control_url, agent_client, ut_id, it_id, injections)
                utility_results[(ut_id, it_id)] = result["utility"]
                security_results[(ut_id, it_id)] = result["security"]
                click.echo(f"  utility={result['utility']}, security={result['security']}")

    logdir.mkdir(parents=True, exist_ok=True)
    results_file = logdir / "results.json"
    with open(results_file, "w") as f:
        json.dump(
            {
                "utility": {f"{k[0]},{k[1]}": v for k, v in utility_results.items()},
                "security": {f"{k[0]},{k[1]}": v for k, v in security_results.items()},
            },
            f,
            indent=2,
        )
    click.echo(f"Results saved to {results_file}")

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
@click.option("--protocol", type=click.Choice(["http", "a2a"]), default="http", help="Agent communication protocol.")
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

    results = asyncio.run(
        run_benchmark(
            control_url=control_url,
            agent_client=agent_client,
            suite=suite,
            attack_name=attack_name,
            user_task_ids=list(user_tasks) if user_tasks else None,
            injection_task_ids=list(injection_tasks) if injection_tasks else None,
            logdir=logdir,
        )
    )

    utility = results["utility_results"]
    if utility:
        avg = sum(utility.values()) / len(utility)
        click.echo(f"Average utility: {avg * 100:.1f}%")

    security = results["security_results"]
    if security:
        avg = sum(security.values()) / len(security)
        click.echo(f"Attack success rate: {avg * 100:.1f}%")


if __name__ == "__main__":
    main()
