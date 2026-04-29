from __future__ import annotations

import click

from midojo.suites import get_suite


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to.")
@click.option("--port", default=8080, type=int, help="Port to bind to.")
@click.option("--suite", "suite_name", default="weather", help="Benchmark suite name.")
@click.option("--real-mcp-url", required=True, help="URL of the real MCP server to forward read calls to.")
def main(host: str, port: int, suite_name: str, real_mcp_url: str) -> None:
    import uvicorn

    from midojo.app.main import create_app

    suite_module = get_suite(suite_name)
    suite = suite_module.task_suite

    from midojo.forwarding import MCPForwardingClient

    MCPForwardingClient.initialize(real_mcp_url)

    passed, (user_results, injection_results) = suite.check()
    if not passed:
        failures = []
        for task_id, (ok, msg) in user_results.items():
            if not ok:
                failures.append(f"  user task {task_id}: {msg}")
        for task_id, ok in injection_results.items():
            if not ok:
                failures.append(f"  injection task {task_id}: not injectable")
        raise SystemExit("Suite preflight check failed:\n" + "\n".join(failures))

    app = create_app(suite, suite_module)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
