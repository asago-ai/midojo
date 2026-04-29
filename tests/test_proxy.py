from unittest.mock import MagicMock

import pytest
from agentdojo.functions_runtime import FunctionsRuntime, make_function

from midojo.forwarding import MCPForwardingClient
from midojo.suites.weather.environment import CityWeather, WeatherEnvironment
from midojo.suites.weather.tools import get_weather, list_cities, send_weather_alert


def _make_weather_env(**overrides) -> WeatherEnvironment:
    defaults = {
        "cities": {
            "New York": CityWeather(city="New York", temperature_f=72.0, condition="Sunny"),
        },
        "weather_alerts": [],
    }
    defaults.update(overrides)
    return WeatherEnvironment(**defaults)


def test_get_instance_raises_when_not_initialized():
    MCPForwardingClient._reset()
    with pytest.raises(RuntimeError, match="ForwardingClient not initialized"):
        MCPForwardingClient.get_instance()


def test_initialize_and_get_instance():
    client = MCPForwardingClient.initialize("http://test:8080/mcp")
    assert MCPForwardingClient.get_instance() is client
    assert client.upstream_url == "http://test:8080/mcp"


def test_is_initialized():
    MCPForwardingClient._reset()
    assert MCPForwardingClient.is_initialized() is False
    MCPForwardingClient.initialize("http://test:8080/mcp")
    assert MCPForwardingClient.is_initialized() is True


def test_get_weather_forwards_and_appends_notes():
    mock_client = MagicMock(spec=MCPForwardingClient)
    mock_client.call_tool.return_value = "Temperature: 72F, Sunny"
    MCPForwardingClient._instance = mock_client

    env = _make_weather_env(
        cities={
            "New York": CityWeather(
                city="New York",
                temperature_f=72.0,
                condition="Sunny",
                notes="INJECTED PAYLOAD",
            ),
        },
    )

    runtime = FunctionsRuntime([make_function(get_weather)])
    result, error = runtime.run_function(env, "get_weather", {"city": "New York"})
    assert error is None
    assert "Temperature: 72F, Sunny" in result
    assert "INJECTED PAYLOAD" in result
    mock_client.call_tool.assert_called_once_with("get_weather", {"city": "New York"})


def test_get_weather_forwards_without_notes():
    mock_client = MagicMock(spec=MCPForwardingClient)
    mock_client.call_tool.return_value = "Temperature: 72F, Sunny"
    MCPForwardingClient._instance = mock_client

    env = _make_weather_env()
    runtime = FunctionsRuntime([make_function(get_weather)])
    result, error = runtime.run_function(env, "get_weather", {"city": "New York"})
    assert error is None
    assert result == "Temperature: 72F, Sunny"


def test_list_cities_forwards():
    mock_client = MagicMock(spec=MCPForwardingClient)
    mock_client.call_tool.return_value = "London\nNew York\nTokyo"
    MCPForwardingClient._instance = mock_client

    env = _make_weather_env()
    runtime = FunctionsRuntime([make_function(list_cities)])
    result, error = runtime.run_function(env, "list_cities", {})
    assert error is None
    assert result == "London\nNew York\nTokyo"
    mock_client.call_tool.assert_called_once_with("list_cities", {})


def test_send_weather_alert_does_not_use_forwarding():
    MCPForwardingClient._reset()

    env = _make_weather_env()
    runtime = FunctionsRuntime([make_function(send_weather_alert)])
    result, error = runtime.run_function(env, "send_weather_alert", {"city": "London", "message": "Flood warning"})
    assert error is None
    assert "Flood warning" in result
    assert len(env.weather_alerts) == 1
    assert env.weather_alerts[0].city == "London"
