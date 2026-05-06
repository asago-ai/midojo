from pathlib import Path

from midojo.suites.weather.a2a_agent import WeatherEnvironment
from midojo.yaml_task_suite import YAMLTaskSuite

DATA_PATH = Path(__file__).resolve().parent / "data"
SUITE_YAML = DATA_PATH / "suite.yaml"

task_suite = YAMLTaskSuite(
    "weather",
    WeatherEnvironment,
    suite_yaml_path=SUITE_YAML,
)
