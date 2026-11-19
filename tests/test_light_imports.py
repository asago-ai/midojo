"""The authoring, generation and grading primitives import without the OpenShell SDK.

Callers that only build suites and grade recorded conversations (a custom evaluation
loop, a red-teaming pipeline) should not need grpc or the OpenShell client loaded to read OpenShell's
observation models or to parse its predicates.
"""

import subprocess
import sys

LIGHT_MODULES = (
    "midojo.attacks",
    "midojo.generator.schema_aware",
    "midojo.grading",
    "midojo.observations",
    "midojo.suite",
    "midojo.verifiers",
)


def test_primitives_do_not_load_the_openshell_sdk():
    script = (
        "import importlib, sys\n"
        f"for name in {LIGHT_MODULES!r}:\n"
        "    importlib.import_module(name)\n"
        "heavy = sorted(m for m in sys.modules if m == 'openshell' or m.startswith(('openshell.', 'grpc')))\n"
        "assert not heavy, heavy\n"
    )
    subprocess.run([sys.executable, "-c", script], check=True)
