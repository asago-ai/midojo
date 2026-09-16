"""An explicitly configured catalog, fully loaded before requests are served."""

from collections.abc import Mapping, Sequence

from pydantic import TypeAdapter

from midojo.suites import get_suite
from midojo.types import SuiteName
from midojo.yaml_task_suite import YAMLTaskSuite

_SUITE_NAME = TypeAdapter(SuiteName)


class SuiteCatalog:
    def __init__(self, suites: Mapping[str, YAMLTaskSuite] | Sequence[str]) -> None:
        names = dict.fromkeys(_SUITE_NAME.validate_python(name) for name in suites)
        if isinstance(suites, Mapping):
            self._suites = {name: suites[name] for name in names}
        else:
            self._suites = {name: get_suite(name) for name in names}

    def list_names(self) -> list[SuiteName]:
        return sorted(self._suites)

    def get(self, suite_name: SuiteName, version: str | None = None) -> YAMLTaskSuite:
        suite = self._suites[suite_name]
        if version is not None and suite.version != version:
            raise ValueError(f"Suite version mismatch: {suite_name}")
        return suite
