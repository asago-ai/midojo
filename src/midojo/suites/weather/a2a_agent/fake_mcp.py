from typing import Annotated

from agentdojo.functions_runtime import Depends

from midojo.forwarding import MCPForwardingClient
from midojo.suites.weather.a2a_agent.environment import CityWeather, WeatherAlert


def get_weather(
    cities: Annotated[dict[str, CityWeather], Depends("cities")],
    city: str,
) -> str:
    """Get current weather for a city.

    :param city: The name of the city to get weather for.
    """
    forward = MCPForwardingClient.get_instance()
    result = forward.call_tool("get_weather", {"city": city})
    if city in cities and cities[city].notes:
        result += "\n" + cities[city].notes
    return result


def list_cities(
    cities: Annotated[dict[str, CityWeather], Depends("cities")],
) -> str:
    """List all cities with available weather data."""
    forward = MCPForwardingClient.get_instance()
    return forward.call_tool("list_cities", {})


def send_weather_alert(
    alerts: Annotated[list[WeatherAlert], Depends("weather_alerts")],
    city: str,
    message: str,
) -> str:
    """Send a weather alert for a city.

    :param city: The city the alert is for.
    :param message: The alert message.
    """
    alerts.append(WeatherAlert(city=city, message=message))
    return f"Weather alert sent for {city}: {message}"
