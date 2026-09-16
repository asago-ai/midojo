from __future__ import annotations

import importlib
from pathlib import Path

from pydantic import TypeAdapter

from midojo.types import SuiteName
from midojo.yaml_task_suite import YAMLTaskSuite

_SUITE_NAME = TypeAdapter(SuiteName)


def list_suites() -> list[str]:
    """Return sorted names of built-in suites (directories under ``suites/`` with a ``suite.yaml``)."""
    suites_dir = Path(importlib.import_module("suites").__file__).parent
    return sorted(p.parent.name for p in suites_dir.glob("*/suite.yaml"))


def get_suite(spec: SuiteName) -> YAMLTaskSuite:
    """Load a suite by name.

    Bare names resolve to ``suites.<name>`` and auto-load ``suite.yaml`` from
    the package directory.  Dotted paths are imported as-is and must expose a
    ``task_suite`` attribute (for out-of-tree suites with custom setup).
    """
    spec = _SUITE_NAME.validate_python(spec)
    if "." in spec:
        module = importlib.import_module(spec)
        return module.task_suite
    module = importlib.import_module(f"suites.{spec}")
    suite_yaml = Path(module.__file__).parent / "suite.yaml"
    return YAMLTaskSuite(spec, suite_yaml_path=suite_yaml)
