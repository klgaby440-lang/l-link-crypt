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
            "crypt_id": "INK_ABCDEFGHJKLMNPQ",
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
    assert payload["user"]["crypt_id"] == "INK_ABCDEFGHJKLMNPQ"
    assert observed["uid"] == "think_thk-0123456789ab"
    assert observed["claims"]["crypt_id"] == "INK_ABCDEFGHJKLMNPQ"
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


def test_authenticated_user_status_is_credit_based():
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
    assert payload["plan"] == "credits"
    assert payload["subscriptionStatus"] == "credits"
    assert payload["expirationDate"] is None


def test_legacy_subscription_checkout_is_disabled():
    main.app.dependency_overrides[users.require_authenticated_user] = lambda: {
        "uid": "think_thk-0123456789ab", "auth_source": "think", "think_user_id": 42,
    }
    try:
        response = client.post(
            "/api/subscriptions/checkout",
            headers={"Idempotency-Key": "legacy-checkout-" + uuid4().hex[:12]},
            json={"plan": "bronze", "payment_method": "AIRTEL_CD"},
        )
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 410, response.text


def test_credit_checkout_requires_think_identity(monkeypatch):
    async def no_quota(**_kwargs):
        return None
    monkeypatch.setattr(users, "enforce_endpoint_quota", no_quota)
    monkeypatch.setattr(users, "get_db", lambda: object())
    main.app.dependency_overrides[users.require_authenticated_user] = lambda: {
        "uid": "legacy-google-user", "email": "legacy@example.test",
    }
    try:
        response = client.post(
            "/api/credits/checkout",
            headers={"Idempotency-Key": "credit-checkout-" + uuid4().hex[:12]},
            json={"credits": 100, "wallet_type": "online", "payment_method": "AIRTEL_CD"},
        )
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 403, response.text


def test_credit_checkout_uses_think_server_and_idempotency(monkeypatch):
    captured = {}

    def fake_checkout(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True, "product": "llink", "credits": 100, "wallet_type": "online",
            "public_id": "PAY-1234567890ABCDEF", "payment_url": "https://checkout.cinetpay.net/pay/test",
            "amount": 2800, "currency": "CDF",
        }

    async def no_quota(**_kwargs):
        return None

    monkeypatch.setattr(users, "create_think_credit_checkout", fake_checkout)
    monkeypatch.setattr(users, "enforce_endpoint_quota", no_quota)
    monkeypatch.setattr(users, "get_db", lambda: object())
    main.app.dependency_overrides[users.require_authenticated_user] = lambda: {
        "uid": "think_thk-0123456789ab", "auth_source": "think", "think_user_id": 42,
    }
    checkout_id = "credit-checkout-" + uuid4().hex[:12]
    try:
        response = client.post(
            "/api/credits/checkout",
            headers={"Idempotency-Key": checkout_id},
            json={"credits": 100, "wallet_type": "online", "payment_method": "AIRTEL_CD"},
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["payment_url"].startswith("https://checkout.cinetpay.net/")
    assert captured == {
        "think_user_id": 42, "credits": 100, "wallet_type": "online",
        "payment_method": "AIRTEL_CD", "checkout_id": checkout_id,
        "mobile_money_account_id": None,
    }


def test_credit_refresh_grants_only_provider_confirmed_purchase(monkeypatch):
    captured = {}

    async def no_quota(**_kwargs):
        return None

    async def fake_grant(**kwargs):
        captured.update(kwargs)
        return {"granted": True, "balance": 100}

    async def fake_wallet(**_kwargs):
        return {"online_balance": 100, "daily_free_balance": 5, "offline_balance": 0}

    monkeypatch.setattr(users, "enforce_endpoint_quota", no_quota)
    monkeypatch.setattr(users, "refresh_think_credit_purchase", lambda **_kwargs: {
        "ok": True, "public_id": "PAY-1234567890ABCDEF", "payment_status": "accepted",
        "credits": {"purchased": 100, "wallet_type": "online", "status": "paid"},
    })
    monkeypatch.setattr(users, "grant_verified_purchase", fake_grant)
    monkeypatch.setattr(users, "read_credit_wallet", fake_wallet)
    monkeypatch.setattr(users, "get_db", lambda: object())
    main.app.dependency_overrides[users.require_authenticated_user] = lambda: {
        "uid": "think_thk-0123456789ab", "auth_source": "think", "think_user_id": 42,
    }
    try:
        response = client.post("/api/credits/refresh", json={"public_id": "PAY-1234567890ABCDEF"})
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["grant"]["granted"] is True
    assert captured["db"] is not None
    assert {key: value for key, value in captured.items() if key != "db"} == {
        "uid": "think_thk-0123456789ab",
        "public_id": "PAY-1234567890ABCDEF", "credits": 100, "wallet_type": "online",
    }
