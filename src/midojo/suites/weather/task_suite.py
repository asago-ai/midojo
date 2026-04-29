from pathlib import Path

from agentdojo.functions_runtime import make_function
from agentdojo.task_suite.task_suite import TaskSuite

from midojo.suites.weather.environment import WeatherEnvironment
from midojo.suites.weather.tools import get_weather, list_cities, send_weather_alert

TOOLS = [get_weather, list_cities, send_weather_alert]

DATA_PATH = Path(__file__).resolve().parent / "data"

task_suite = TaskSuite[WeatherEnvironment](
    "weather",
    WeatherEnvironment,
    [make_function(tool) for tool in TOOLS],
    data_path=DATA_PATH,
)
