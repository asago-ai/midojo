from __future__ import annotations

import importlib
from pathlib import Path

from midojo.yaml_task_suite import YAMLTaskSuite


def get_suite(spec: str) -> YAMLTaskSuite:
    """Load a suite by name.

    Bare names resolve to ``suites.<name>`` and auto-load ``suite.yaml`` from
    the package directory.  Dotted paths are imported as-is and must expose a
    ``task_suite`` attribute (for out-of-tree suites with custom setup).
    """
    if "." in spec:
        module = importlib.import_module(spec)
        return module.task_suite
    module = importlib.import_module(f"suites.{spec}")
    suite_yaml = Path(module.__file__).parent / "suite.yaml"
    return YAMLTaskSuite(spec, suite_yaml_path=suite_yaml)
