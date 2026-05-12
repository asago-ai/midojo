from pathlib import Path

from suites.weather.a2a_agent import WeatherEnvironment
from midojo.yaml_task_suite import YAMLTaskSuite

SUITE_YAML = Path(__file__).resolve().parent / "suite.yaml"

task_suite = YAMLTaskSuite(
    "weather",
    WeatherEnvironment,
    suite_yaml_path=SUITE_YAML,
)
