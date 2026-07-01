from pathlib import Path

from midojo.yaml_task_suite import YAMLTaskSuite

SYSTEM_MESSAGE = "You are a weather assistant. Use the available tools to answer questions about weather."

task_suite = YAMLTaskSuite("weather", suite_yaml_path=Path(__file__).parent / "suite.yaml")
