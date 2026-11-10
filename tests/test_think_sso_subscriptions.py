import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("THINK_SSO_SECRET", "test-sso-secret-" + ("x" * 48))
os.environ.setdefault("THINK_SERVICE_TOKEN", "test-service-token-" + ("y" * 48))
os.environ.setdefault("THINK_API_BASE_URL", "https://think.example.test")

import jwt
import pytest
from fastapi.testclient import TestClient

import main
from llink_api.api.routes import users
from llink_api.services import entitlements


client = TestClient(main.app)


def _sso_token(*, jti: str | None = None, scope: str = "llink", expires: int = 120) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "42",
            "think_id": "THK-0123456789AB",
            "email": "tester@example.test",
            "name": "Think Tester",
            "scope": scope,
            "iss": "think-api",
            "aud": "llink-api",
            "iat": now,
            "exp": now + timedelta(seconds=expires),
            "jti": jti or uuid4().hex,
        },
        os.environ["THINK_SSO_SECRET"],
        algorithm="HS256",
    )


def test_think_sso_exchange_creates_firebase_custom_token(monkeypatch):
    observed = {}

    def fake_create_custom_token(uid, developer_claims=None):
        observed["uid"] = uid
        observed["claims"] = developer_claims
        return b"firebase-custom-token"

    monkeypatch.setattr(users.firebase_auth, "create_custom_token", fake_create_custom_token)
    response = client.post("/api/auth/think-exchange", json={"sso_token": _sso_token()})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["customToken"] == "firebase-custom-token"
    assert payload["user"]["think_id"] == "THK-0123456789AB"
    assert observed["uid"] == "think_thk-0123456789ab"
    assert observed["claims"]["auth_source"] == "think"
    assert observed["claims"]["think_user_id"] == 42


def test_think_sso_exchange_rejects_replayed_ticket(monkeypatch):
    monkeypatch.setattr(users.firebase_auth, "create_custom_token", lambda *args, **kwargs: "custom-token")
    token = _sso_token(jti="replay-" + uuid4().hex)

    first = client.post("/api/auth/think-exchange", json={"sso_token": token})
    second = client.post("/api/auth/think-exchange", json={"sso_token": token})

    assert first.status_code == 200, first.text
    assert second.status_code == 401, second.text


def test_think_sso_exchange_rejects_wrong_scope(monkeypatch):
    monkeypatch.setattr(users.firebase_auth, "create_custom_token", lambda *args, **kwargs: "custom-token")
    response = client.post("/api/auth/think-exchange", json={"sso_token": _sso_token(scope="think")})
    assert response.status_code == 401, response.text


def test_think_sso_exchange_rejects_expired_ticket():
    response = client.post("/api/auth/think-exchange", json={"sso_token": _sso_token(expires=-10)})
    assert response.status_code == 401, response.text


def test_think_user_status_uses_think_subscription(monkeypatch):
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=30)).isoformat()
    monkeypatch.setattr(
        users,
        "get_think_subscription",
        lambda user_id: {
            "is_active": True,
            "plan": "gold",
            "status": "active",
            "expires_at": expires_at,
            "level": "auren",
        },
    )
    monkeypatch.setattr(
        users,
        "get_optional_user",
        lambda: {
            "uid": "think_thk-0123456789ab",
            "auth_source": "think",
            "think_user_id": 42,
        },
    )
    main.app.dependency_overrides[users.get_optional_user] = lambda: {
        "uid": "think_thk-0123456789ab",
        "auth_source": "think",
        "think_user_id": 42,
    }
    try:
        response = client.get("/api/user/status")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["isValid"] is True
    assert payload["isTrial"] is False
    assert payload["plan"] == "gold"
    assert payload["subscriptionStatus"] == "active"


def test_checkout_requires_think_linked_identity(monkeypatch):
    main.app.dependency_overrides[users.require_authenticated_user] = lambda: {
        "uid": "legacy-google-user",
        "email": "legacy@example.test",
    }
    try:
        response = client.post(
            "/api/subscriptions/checkout",
            headers={"Idempotency-Key": "checkout-" + uuid4().hex[:16]},
            json={"plan": "bronze", "payment_method": "AIRTEL_CD"},
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 403, response.text


def test_checkout_uses_server_billing_service_and_idempotency(monkeypatch):
    captured = {}

    def fake_checkout(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "product": "llink",
            "plan": kwargs["plan"],
            "public_id": "PAY-TEST-12345678",
            "payment_url": "https://checkout.cinetpay.net/pay/test",
            "amount": 500,
            "currency": "CDF",
        }

    monkeypatch.setattr(users, "create_think_subscription_checkout", fake_checkout)
    main.app.dependency_overrides[users.require_authenticated_user] = lambda: {
        "uid": "think_thk-0123456789ab",
        "auth_source": "think",
        "think_user_id": 42,
    }
    checkout_id = "checkout-" + uuid4().hex[:16]
    try:
        response = client.post(
            "/api/subscriptions/checkout",
            headers={"Idempotency-Key": checkout_id},
            json={
                "plan": "bronze",
                "payment_method": "AIRTEL_CD",
                "mobile_money_account_id": 7,
                "amount": 1,
            },
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["payment_url"].startswith("https://checkout.cinetpay.net/")
    assert captured == {
        "think_user_id": 42,
        "plan": "bronze",
        "payment_method": "AIRTEL_CD",
        "checkout_id": checkout_id,
        "mobile_money_account_id": 7,
    }
    assert "amount" not in captured


def test_think_subscription_status_is_the_only_entitlement_source(monkeypatch):
    monkeypatch.setattr(
        entitlements,
        "get_think_subscription",
        lambda user_id: {"is_active": True, "level": "noetra"},
    )
    assert entitlements.resolve_entitled_level(
        {"uid": "think_thk-0123456789ab", "auth_source": "think", "think_user_id": 42},
        db=None,
    ) == "noetra"

    monkeypatch.setattr(
        entitlements,
        "get_think_subscription",
        lambda user_id: {"is_active": False, "level": "omnis"},
    )
    assert entitlements.resolve_entitled_level(
        {"uid": "think_thk-0123456789ab", "auth_source": "think", "think_user_id": 42},
        db=None,
    ) == "velora"
