from unittest.mock import MagicMock

import pytest

import midojo.suites.weather.injection_tasks
import midojo.suites.weather.user_tasks  # noqa: F401
from midojo.forwarding import MCPForwardingClient
from midojo.suites.weather import task_suite


@pytest.fixture(autouse=True)
def _mock_forwarding_client():
    original = MCPForwardingClient._instance
    mock = MagicMock(spec=MCPForwardingClient)
    mock.call_tool.return_value = ""
    MCPForwardingClient._instance = mock
    yield
    MCPForwardingClient._instance = original


@pytest.fixture
def suite():
    return task_suite


@pytest.fixture
def environment():
    return task_suite.load_and_inject_default_environment({})
