from __future__ import annotations

import click
import uvicorn

from midojo.app.main import create_app
from midojo.suites import list_suites


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to.")
@click.option("--port", default=8080, type=int, help="Port to bind to.")
@click.option(
    "--suite-package",
    multiple=True,
    help="Installed external suite module to add to the built-in catalog. Repeat for multiple packages.",
)
@click.option("--session-ttl", default=3600, type=click.IntRange(min=1), help="Evaluation session lifetime in seconds.")
def main(host: str, port: int, suite_package: tuple[str, ...], session_ttl: int) -> None:
    app = create_app([*list_suites(), *suite_package], session_ttl_seconds=session_ttl)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
