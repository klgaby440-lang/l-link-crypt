import os

from fastapi.testclient import TestClient

import main
from llink_api.api.routes import crypt_console


def test_crypt_console_internal_routes_fail_closed_without_service_secret(monkeypatch):
    monkeypatch.delenv("CRYPT_CONSOLE_SERVICE_TOKEN", raising=False)
    with TestClient(main.app) as client:
        response = client.get("/api/internal/crypt-console/overview")
    assert response.status_code == 503


def test_crypt_console_internal_routes_reject_invalid_service_token(monkeypatch):
    monkeypatch.setenv("CRYPT_CONSOLE_SERVICE_TOKEN", "test-console-secret-" + ("x" * 40))
    with TestClient(main.app) as client:
        response = client.get(
            "/api/internal/crypt-console/overview",
            headers={"X-CRYPT-CONSOLE-TOKEN": "wrong-token"},
        )
    assert response.status_code == 401


def test_crypt_console_internal_routes_require_firestore(monkeypatch):
    monkeypatch.setenv("CRYPT_CONSOLE_SERVICE_TOKEN", "test-console-secret-" + ("x" * 40))
    monkeypatch.setattr(crypt_console, "get_db", lambda: None)
    with TestClient(main.app) as client:
        response = client.get(
            "/api/internal/crypt-console/overview",
            headers={"X-CRYPT-CONSOLE-TOKEN": os.environ["CRYPT_CONSOLE_SERVICE_TOKEN"]},
        )
    assert response.status_code == 503
