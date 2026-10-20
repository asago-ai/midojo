import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from midojo.control_plane.main import create_app
from midojo.suites import get_suite

# The weather suite requires its model server settings to load. Tests never
# start its agent, so placeholders do.
os.environ.setdefault("LITELLM_API_HOST", "model-server.test")
os.environ.setdefault("LITELLM_MODEL", "test-model")

task_suite = get_suite("weather")


@pytest.fixture(autouse=True)
def no_control_token(monkeypatch):
    """Tests run without a control token unless they set MIDOJO_CONTROL_TOKEN themselves."""
    monkeypatch.delenv("MIDOJO_CONTROL_TOKEN", raising=False)


@pytest.fixture
def suite():
    return task_suite


@pytest.fixture
def environment():
    return task_suite.provision_environment({})


@pytest.fixture()
def app() -> FastAPI:
    return create_app({"weather": task_suite})


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)
