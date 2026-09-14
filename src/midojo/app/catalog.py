"""An operator-configured catalog; requests cannot import arbitrary Python modules."""

from collections.abc import Mapping, Sequence
from threading import RLock

from midojo.suites import get_suite, list_suites
from midojo.yaml_task_suite import YAMLTaskSuite


class SuiteCatalog:
    def __init__(self, suites: Mapping[str, YAMLTaskSuite] | Sequence[str] | None = None) -> None:
        self._loaded = dict(suites) if isinstance(suites, Mapping) else {}
        self._ids = set(suites if suites is not None else list_suites())
        self._lock = RLock()

    def list_ids(self) -> list[str]:
        return sorted(self._ids)

    def get(self, suite_id: str, version: str | None = None) -> YAMLTaskSuite:
        with self._lock:
            if suite_id not in self._ids:
                raise KeyError(suite_id)
            if suite_id not in self._loaded:
                self._loaded[suite_id] = get_suite(suite_id)
            suite = self._loaded[suite_id]
            if version is not None and suite.version != version:
                raise ValueError(f"Suite version mismatch: {suite_id}")
            return suite
