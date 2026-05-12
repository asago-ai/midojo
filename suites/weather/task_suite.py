from pathlib import Path

from midojo.yaml_task_suite import YAMLTaskSuite

SUITE_YAML = Path(__file__).resolve().parent / "suite.yaml"

task_suite = YAMLTaskSuite(
    "weather",
    suite_yaml_path=SUITE_YAML,
)
