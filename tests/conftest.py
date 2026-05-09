import pytest

from suites.weather import task_suite


@pytest.fixture
def suite():
    return task_suite


@pytest.fixture
def environment():
    return task_suite.load_and_inject_default_environment({})
