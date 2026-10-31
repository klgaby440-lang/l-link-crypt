import pytest
from fastapi.testclient import TestClient

from llink_api.services.ai_slots import reset_ai_slots_for_tests
from llink_api.services.security_limits import reset_memory_quotas_for_tests
from main import app


@pytest.fixture(autouse=True)
def reset_process_local_protections():
    reset_memory_quotas_for_tests()
    reset_ai_slots_for_tests()
    yield
    reset_memory_quotas_for_tests()
    reset_ai_slots_for_tests()


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client
