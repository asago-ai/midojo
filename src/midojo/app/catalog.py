"""An operator-configured catalog; requests cannot import arbitrary Python modules."""

from collections.abc import Mapping, Sequence
from threading import RLock

from midojo.suites import get_suite, list_suites
from midojo.yaml_task_suite import YAMLTaskSuite


class SuiteCatalog:
    def __init__(self, suites: Mapping[str, YAMLTaskSuite] | Sequence[str] | None = None) -> None:
        self._loaded = dict(suites) if isinstance(suites, Mapping) else {}
        self._names = set(suites if suites is not None else list_suites())
        self._lock = RLock()

    def list_names(self) -> list[str]:
        return sorted(self._names)

    def get(self, suite_name: str, version: str | None = None) -> YAMLTaskSuite:
        with self._lock:
            if suite_name not in self._names:
                raise KeyError(suite_name)
            if suite_name not in self._loaded:
                self._loaded[suite_name] = get_suite(suite_name)
            suite = self._loaded[suite_name]
            if version is not None and suite.version != version:
                raise ValueError(f"Suite version mismatch: {suite_name}")
            return suite
