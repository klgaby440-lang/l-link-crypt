"""Tests des autorisations, de l'anti-abus et des limites d'usage."""

from fastapi import HTTPException

from llink_api import security


def test_history_read_requires_authentication(client):
    response = client.get("/api/history")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_history_sync_requires_authentication(client):
    response = client.post(
        "/api/history/sync",
        json={"id": 1, "title": "Private", "messages": []},
    )
    assert response.status_code == 401


def test_payment_verification_requires_authentication(client):
    response = client.post(
        "/api/verify-payment",
        json={"transactionId": "TEST-REFERENCE"},
    )
    assert response.status_code == 401


def test_invalid_bearer_is_never_downgraded_to_anonymous(client, monkeypatch):
    def reject(_token):
        raise HTTPException(status_code=401, detail="Jeton Firebase invalide.")

    monkeypatch.setattr(security, "_decode_firebase_token", reject)
    response = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer invalid-token"},
        json={"message": "Bonjour", "model": "gemini-1.5-flash"},
    )
    assert response.status_code == 401


def test_authenticated_private_route_fails_closed_without_firestore(client, monkeypatch):
    monkeypatch.setattr(
        security, "_decode_firebase_token", lambda _token: {"uid": "test-user"}
    )
    response = client.get(
        "/api/history",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert response.status_code == 503
    assert "Stockage" in response.json()["detail"]


def test_invalid_authorization_scheme_is_rejected(client):
    response = client.post(
        "/api/chat",
        headers={"Authorization": "Basic abc123"},
        json={"message": "Bonjour", "model": "gemini-1.5-flash"},
    )
    assert response.status_code == 401


def test_anonymous_chat_quota_returns_429(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    payload = {"message": "Ping", "model": "gemini-1.5-flash"}

    for _ in range(3):
        response = client.post("/api/chat", json=payload)
        assert response.status_code == 200

    limited = client.post("/api/chat", json=payload)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


def test_production_fails_closed_when_firestore_quota_store_is_unavailable(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    response = client.post(
        "/api/chat",
        json={"message": "Ping", "model": "gemini-1.5-flash"},
    )
    assert response.status_code == 503
    assert "quotas" in response.json()["detail"]
