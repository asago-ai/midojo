import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from midojo.app.main import create_app
from midojo.suites import get_suite

task_suite = get_suite("weather")


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
