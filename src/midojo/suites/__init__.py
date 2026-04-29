from __future__ import annotations

import importlib
from types import ModuleType


def get_suite(name: str) -> ModuleType:
    """Import and return a suite module by name."""
    return importlib.import_module(f"midojo.suites.{name}")


def list_suites() -> list[str]:
    """Return names of available benchmark suites."""
    return ["weather"]
