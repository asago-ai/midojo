from pathlib import Path

from midojo.yaml_task_suite import YAMLTaskSuite

task_suite = YAMLTaskSuite(
    "openshell_network_escape",
    suite_yaml_path=Path(__file__).parent / "suite.yaml",
)
