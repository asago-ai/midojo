from __future__ import annotations

import click
import uvicorn

from midojo.app.main import create_app
from midojo.suites import get_suite


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to.")
@click.option("--port", default=8080, type=int, help="Port to bind to.")
@click.option("--suite", "suite_name", default="weather", help="Benchmark suite name.")
def main(host: str, port: int, suite_name: str) -> None:
    suite = get_suite(suite_name)

    app = create_app(suite)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
