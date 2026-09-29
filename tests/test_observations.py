import pytest
from pydantic import BaseModel

from midojo.backends.openshell import OBSERVATIONS_SOURCE, OpenShellObservations
from midojo.observations import observation_type, register_observation_type


def test_openshell_registers_its_observation_type():
    assert observation_type(OBSERVATIONS_SOURCE) is OpenShellObservations


def test_unknown_source_has_no_type():
    assert observation_type("unregistered") is None


def test_a_source_keeps_its_first_model():
    class Other(BaseModel):
        pass

    register_observation_type(OBSERVATIONS_SOURCE, OpenShellObservations)  # the same model again is a no-op
    with pytest.raises(ValueError, match="already registered"):
        register_observation_type(OBSERVATIONS_SOURCE, Other)
    assert observation_type(OBSERVATIONS_SOURCE) is OpenShellObservations
