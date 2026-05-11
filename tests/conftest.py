import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from midojo.app import state
from midojo.app.routers import runs
from suites.weather import task_suite


@pytest.fixture
def suite():
    return task_suite


@pytest.fixture
def environment():
    return task_suite.load_and_inject_default_environment({})


@pytest.fixture()
def app() -> FastAPI:
    state.suite = task_suite
    state.runs = {}
    state.current_eval = None
    application = FastAPI()
    runs.register_environment_update_route(task_suite.environment_type)
    application.include_router(runs.router)
    application.include_router(runs.current_router)
    return application


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)
