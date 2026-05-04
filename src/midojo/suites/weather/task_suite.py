from pathlib import Path

from agentdojo.functions_runtime import make_function

from midojo.yaml_task_suite import YAMLTaskSuite
from midojo.suites.weather.a2a_agent import WeatherEnvironment, get_weather, list_cities, send_weather_alert

TOOLS = [get_weather, list_cities, send_weather_alert]

DATA_PATH = Path(__file__).resolve().parent / "data"
SUITE_YAML = DATA_PATH / "suite.yaml"

task_suite = YAMLTaskSuite(
    "weather",
    WeatherEnvironment,
    [make_function(tool) for tool in TOOLS],
    suite_yaml_path=SUITE_YAML,
)
