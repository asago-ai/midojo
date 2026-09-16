from __future__ import annotations

import click
import uvicorn

from midojo.app.config import AppConfig
from midojo.app.main import create_app
from midojo.suites import list_suites


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to.")
@click.option("--port", default=8080, type=int, help="Port to bind to.")
@click.option(
    "--load-suite",
    multiple=True,
    metavar="NAME_OR_MODULE",
    help="Add an installed suite to the built-in catalog by name or module path. Repeat to add more suites.",
)
@click.option(
    "--session-ttl",
    default=AppConfig().session_ttl_seconds,
    type=click.IntRange(min=1),
    help="Evaluation session lifetime in seconds.",
)
def main(host: str, port: int, load_suite: tuple[str, ...], session_ttl: int) -> None:
    config = AppConfig(session_ttl_seconds=session_ttl)
    app = create_app([*list_suites(), *load_suite], config=config)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
