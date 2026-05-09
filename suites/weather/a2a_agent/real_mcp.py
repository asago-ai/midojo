"""Standalone MCP server providing real weather tools.

Start this server and pass its URL as --upstream-url to weather-mcp-serve
so the fake MCP server forwards read calls here.
"""

from __future__ import annotations

import click
from fastmcp import FastMCP

mcp = FastMCP("weather")

REAL_WEATHER_DATA = {
    "New York": {"temperature_f": 72.0, "condition": "sunny"},
    "San Francisco": {"temperature_f": 58.0, "condition": "foggy"},
    "Chicago": {"temperature_f": 45.0, "condition": "windy"},
}


@mcp.tool()
def get_weather(city: str) -> str:
    """Get current weather for a city.

    :param city: The name of the city to get weather for.
    """
    if city not in REAL_WEATHER_DATA:
        return f"No weather data available for {city}"
    w = REAL_WEATHER_DATA[city]
    return f"{city}: {w['temperature_f']}°F, {w['condition']}"


@mcp.tool()
def list_cities() -> str:
    """List all cities with available weather data."""
    return ", ".join(REAL_WEATHER_DATA.keys())


@mcp.tool()
def send_weather_alert(city: str, message: str) -> str:
    """Send a weather alert for a city.

    No-op here. Write tools typically don't forward to the real server because
    their benchmark counterparts operate on the simulated environment to
    capture mutations for grading.

    :param city: The city the alert is for.
    :param message: The alert message.
    """
    return f"Weather alert sent for {city}: {message}"


@click.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to.")
@click.option("--port", default=8081, type=int, help="Port to bind to.")
def main(host: str, port: int) -> None:
    import uvicorn

    app = mcp.http_app(path="/mcp")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
