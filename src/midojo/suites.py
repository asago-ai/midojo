from __future__ import annotations

import importlib
from types import ModuleType


def get_suite(spec: str) -> ModuleType:
    """Import a suite module.

    Bare names resolve to ``suites.<name>`` (the bundled location); dotted paths
    are imported as-is, so out-of-tree suites can be loaded by their full module
    path (e.g. ``my_pkg.my_suite``).
    """
    if "." in spec:
        return importlib.import_module(spec)
    return importlib.import_module(f"suites.{spec}")
