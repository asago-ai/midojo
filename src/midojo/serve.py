from __future__ import annotations

import click
import uvicorn
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.task_suite import GroundTruthPipeline, is_task_injectable
from rich.console import Console
from rich.text import Text

from midojo.app.main import create_app
from midojo.forwarding import MCPForwardingClient
from midojo.suites import get_suite

console = Console()


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to.")
@click.option("--port", default=8080, type=int, help="Port to bind to.")
@click.option("--suite", "suite_name", default="weather", help="Benchmark suite name.")
@click.option("--real-mcp-url", required=True, help="URL of the real MCP server to forward read calls to.")
def main(host: str, port: int, suite_name: str, real_mcp_url: str) -> None:
    suite_module = get_suite(suite_name)
    suite = suite_module.task_suite

    MCPForwardingClient.initialize(real_mcp_url)

    _, (user_results, injection_results) = suite.check(check_injectable=False)

    canary_injections = {inj: f"---CANARY_{inj}---" for inj in suite.get_injection_vector_defaults()}
    canary_env = suite.load_and_inject_default_environment(canary_injections)

    has_errors = False
    console.print("\n[bold]Suite preflight check[/bold]")
    for task_id, (ok, msg) in user_results.items():
        user_task = suite.user_tasks[task_id]
        if not ok:
            status = Text(f"✗ {msg}", style="bold red")
            has_errors = True
        else:
            gt = GroundTruthPipeline(user_task)
            runtime = FunctionsRuntime(suite.tools)
            _, _, _, responses, _ = gt.query(user_task.PROMPT, runtime, canary_env.model_copy(deep=True))
            injectable = is_task_injectable(responses, list(canary_injections.values()))
            if injectable:
                status = Text("✓ ok (injectable)", style="bold green")
            else:
                status = Text("✓ ok (not injectable)", style="yellow")
        console.print(f"  {task_id}: ", status)
    for task_id, ok in injection_results.items():
        if ok:
            status = Text("✓ ok", style="bold green")
        else:
            status = Text("✗ ground truth does not solve task", style="bold red")
            has_errors = True
        console.print(f"  {task_id}: ", status)
    console.print()
    if has_errors:
        raise SystemExit("Suite preflight check failed — fix errors above before starting.")

    app = create_app(suite, suite_module)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
