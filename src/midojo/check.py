"""midojo-check — validate suite tasks against the real fake MCP tools.

Calls the fake MCP server directly (no agent) using ground truth tool calls
from suite.yaml to check:

1. User task achievability — do ground truth calls produce correct results?
2. User task injectability — which vectors reach which tools?
3. Injection task achievability — do injection ground truth calls satisfy security?
"""

from __future__ import annotations

import asyncio
from typing import Any

import click
import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from rich.console import Console
from rich.text import Text

from midojo.suites import get_suite
from midojo.yaml_task_suite import YAMLTaskSuite

console = Console()


async def _create_run(control_url: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{control_url}/runs")
        resp.raise_for_status()
        return resp.json()["id"]


async def _create_eval(
    control_url: str,
    run_id: str,
    user_task_id: str,
    injection_task_id: str | None,
    injections: dict[str, str],
) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{control_url}/runs/{run_id}/evaluations",
            json={
                "user_task_id": user_task_id,
                "injection_task_id": injection_task_id,
                "injections": injections,
            },
        )
        resp.raise_for_status()
        return resp.json()["id"]


async def _complete_and_grade(
    control_url: str, run_id: str, eval_id: str, model_output: str
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{control_url}/runs/{run_id}/evaluations/{eval_id}/complete",
            json={"model_output": model_output},
        )
        resp.raise_for_status()
        resp = await client.post(
            f"{control_url}/runs/{run_id}/evaluations/{eval_id}/grade",
        )
        resp.raise_for_status()
        return resp.json()


async def _call_tools_via_mcp(
    mcp_url: str,
    tool_calls: list[dict[str, Any]],
) -> list[str]:
    """Execute tool calls via MCP and return text results."""
    results: list[str] = []
    async with streamablehttp_client(mcp_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            for tc in tool_calls:
                result = await session.call_tool(tc["function"], tc["args"])
                parts = []
                for block in result.content:
                    if hasattr(block, "text"):
                        parts.append(block.text)
                results.append("\n".join(parts))
    return results


async def check_user_tasks(
    control_url: str,
    mcp_url: str,
    run_id: str,
    suite: YAMLTaskSuite,
) -> None:
    console.print("\n[bold]User Tasks[/bold]")
    for task_id, task in suite.user_tasks.items():
        gt_calls = task.ground_truth(None)
        tool_calls = [{"function": fc.function, "args": fc.args} for fc in gt_calls]

        eval_id = await _create_eval(control_url, run_id, task_id, None, {})
        results = await _call_tools_via_mcp(mcp_url, tool_calls)
        model_output = task.GROUND_TRUTH_OUTPUT or "\n".join(results)
        grade = await _complete_and_grade(control_url, run_id, eval_id, model_output)

        achievable = grade["utility"]
        status = Text("achievable ✓", style="bold green") if achievable else Text("NOT achievable ✗", style="bold red")
        console.print(f"  {task_id:30s}", status)


async def check_injectability(
    control_url: str,
    mcp_url: str,
    run_id: str,
    suite: YAMLTaskSuite,
) -> None:
    console.print("\n[bold]Injectability[/bold]")
    vectors = suite.get_injection_vector_defaults()
    if not vectors:
        console.print("  [dim]No injection vectors defined[/dim]")
        return

    canaries = {v: f"---CANARY_{v}---" for v in vectors}

    for task_id, task in suite.user_tasks.items():
        gt_calls = task.ground_truth(None)
        tool_calls = [{"function": fc.function, "args": fc.args} for fc in gt_calls]

        eval_id = await _create_eval(control_url, run_id, task_id, None, canaries)
        results = await _call_tools_via_mcp(mcp_url, tool_calls)
        await _complete_and_grade(control_url, run_id, eval_id, "\n".join(results))

        hit_vectors: dict[str, list[str]] = {}
        for tc, result_text in zip(tool_calls, results):
            for vec_name, canary in canaries.items():
                if canary in result_text:
                    hit_vectors.setdefault(vec_name, []).append(tc["function"])

        if hit_vectors:
            parts = []
            for vec, fns in hit_vectors.items():
                parts.append(f"{', '.join(fns)} → {vec}")
            console.print(f"  {task_id:30s}", Text(f"injectable via: {'; '.join(parts)}", style="bold yellow"))
        else:
            console.print(f"  {task_id:30s}", Text("not injectable", style="dim"))


async def check_injection_tasks(
    control_url: str,
    mcp_url: str,
    run_id: str,
    suite: YAMLTaskSuite,
) -> None:
    console.print("\n[bold]Injection Tasks[/bold]")
    carrier_user_task_id = next(iter(suite.user_tasks))

    for task_id, task in suite.injection_tasks.items():
        gt_calls = task.ground_truth(None)
        tool_calls = [{"function": fc.function, "args": fc.args} for fc in gt_calls]

        eval_id = await _create_eval(
            control_url, run_id, carrier_user_task_id, task_id, {}
        )
        results = await _call_tools_via_mcp(mcp_url, tool_calls)
        model_output = "\n".join(results)
        grade = await _complete_and_grade(control_url, run_id, eval_id, model_output)

        achievable = grade["security"]
        status = Text("achievable ✓", style="bold green") if achievable else Text("NOT achievable ✗", style="bold red")
        console.print(f"  {task_id:30s}", status)


async def run_checks(control_url: str, mcp_url: str, suite: YAMLTaskSuite, suite_name: str) -> None:
    console.print(f"[bold cyan]midojo-check[/bold cyan] — suite: [bold]{suite_name}[/bold]")

    run_id = await _create_run(control_url)
    console.print(f"  [dim]run[/dim] [cyan]{run_id}[/cyan]")

    await check_user_tasks(control_url, mcp_url, run_id, suite)
    await check_injectability(control_url, mcp_url, run_id, suite)
    await check_injection_tasks(control_url, mcp_url, run_id, suite)

    console.print()


@click.command()
@click.option("--control-url", default="http://localhost:8080", help="Control plane URL.")
@click.option("--mcp-url", required=True, help="Fake MCP server URL (e.g. http://localhost:8081/mcp).")
@click.option("--suite", "suite_name", default="weather", help="Suite name.")
def main(control_url: str, mcp_url: str, suite_name: str) -> None:
    suite_module = get_suite(suite_name)
    suite = suite_module.task_suite
    asyncio.run(run_checks(control_url, mcp_url, suite, suite_name))


if __name__ == "__main__":
    main()
