from __future__ import annotations

import click
import uvicorn

from midojo.app.config import AppConfig
from midojo.app.main import create_app
from midojo.suites import get_suite


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to.")
@click.option("--port", default=8080, type=int, help="Port to bind to.")
@click.option(
    "--load-suite",
    multiple=True,
    required=True,
    metavar="NAME_OR_MODULE",
    help="Load a suite at startup by name or module path. Repeat to expose multiple suites.",
)
@click.option(
    "--session-ttl",
    default=AppConfig().session_ttl_seconds,
    type=click.IntRange(min=1),
    help="Evaluation session lifetime in seconds.",
)
def main(host: str, port: int, load_suite: tuple[str, ...], session_ttl: int) -> None:
    config = AppConfig(session_ttl_seconds=session_ttl)
    suites = {name: get_suite(name) for name in dict.fromkeys(load_suite)}
    app = create_app(suites, config=config)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
