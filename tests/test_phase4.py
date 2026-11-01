"""Tests de la Phase 4 : export, suppressions et contrôle d'accès aux données."""

import json
import time

import pytest

from llink_api import security
from llink_api.api.routes import data as data_routes
from llink_api.database import get_db
from main import app
from llink_api.services.security_limits import (
    _quota_document_id,
    delete_user_rate_limit_records,
    get_quota_policy,
)


class FakeSnapshot:
    def __init__(self, reference):
        self.reference = reference
        self.id = reference.id
        self.exists = reference._data is not None
        self._data = reference._data

    def to_dict(self):
        return self._data


class FakeDocument:
    def __init__(self, collection, document_id):
        self._collection = collection
        self.id = document_id
        self._data = None
        self._collections = {}

    @property
    def reference(self):
        return self

    def get(self, **_kwargs):
        return FakeSnapshot(self)

    def set(self, data):
        self._data = dict(data)

    def delete(self):
        self._data = None

    def collection(self, name):
        if name not in self._collections:
            self._collections[name] = FakeCollection(self, name)
        return self._collections[name]

    def collections(self):
        return list(self._collections.values())


class FakeQuery:
    def __init__(self, collection, field, value):
        self.collection = collection
        self.field = field
        self.value = value

    def stream(self):
        for document in self.collection._documents.values():
            if document._data and document._data.get(self.field) == self.value:
                yield FakeSnapshot(document)


class FakeCollection:
    def __init__(self, parent, name):
        self.parent = parent
        self.id = name
        self._documents = {}

    def document(self, document_id):
        if document_id not in self._documents:
            self._documents[document_id] = FakeDocument(self, document_id)
        return self._documents[document_id]

    def stream(self):
        for document in self._documents.values():
            if document._data is not None or any(list(child.stream()) for child in document.collections()):
                yield FakeSnapshot(document)

    def where(self, field, operator, value):
        assert operator == "=="
        return FakeQuery(self, field, value)


class FakeBatch:
    def __init__(self):
        self.references = []

    def delete(self, reference):
        self.references.append(reference)

    def commit(self):
        for reference in self.references:
            reference.delete()


class FakeFirestore:
    def __init__(self):
        self._collections = {}

    def collection(self, name):
        if name not in self._collections:
            self._collections[name] = FakeCollection(self, name)
        return self._collections[name]

    def batch(self):
        return FakeBatch()


@pytest.fixture
def firestore_db():
    db = FakeFirestore()
    app.dependency_overrides[get_db] = lambda: db
    yield db
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def authenticated_token(monkeypatch):
    def decode(_token):
        return {"uid": "phase4-user", "auth_time": time.time()}

    monkeypatch.setattr(security, "_decode_firebase_token", decode)
    return {"Authorization": "Bearer phase4-token"}


@pytest.fixture
def no_quota(monkeypatch):
    async def allow(**_kwargs):
        return None

    monkeypatch.setattr(data_routes, "enforce_endpoint_quota", allow)


def test_phase4_private_data_routes_require_authentication(client):
    assert client.get("/api/data/export").status_code == 401
    assert client.request(
        "DELETE",
        "/api/account",
        json={"confirmation": "SUPPRIMER MON COMPTE"},
    ).status_code == 401
    assert client.delete("/api/history").status_code == 401
    assert client.delete("/api/history/chat-1").status_code == 401


def test_phase4_routes_are_in_openapi(client):
    schema = client.get("/openapi.json").json()
    assert "/api/data/export" in schema["paths"]
    assert "get" in schema["paths"]["/api/data/export"]
    assert "delete" in schema["paths"]["/api/history"]
    assert "delete" in schema["paths"]["/api/history/{sync_id}"]
    assert "delete" in schema["paths"]["/api/account"]


def test_data_export_includes_user_document_and_subcollections(
    client, firestore_db, authenticated_token, no_quota
):
    user_ref = firestore_db.collection("users").document("phase4-user")
    user_ref.set({"email": "user@example.test", "isPro": False})
    user_ref.collection("chats").document("chat-1").set({
        "title": "Discussion privée",
        "messages": [{"role": "user", "text": "Bonjour"}],
    })
    user_ref.collection("usage_hours").document("hour-1").set({
        "request_count": 2,
        "estimated_cost_usd": 0.001,
    })

    response = client.get("/api/data/export", headers=authenticated_token)

    assert response.status_code == 200
    assert "attachment;" in response.headers["content-disposition"]
    payload = response.json()
    assert payload["format"] == "llink-personal-data-export"
    assert payload["account"]["email"] == "user@example.test"
    assert payload["account"]["chats"][0]["_document_id"] == "chat-1"
    assert payload["account"]["usage_hours"][0]["request_count"] == 2


def test_delete_single_history_item_is_idempotent_and_scoped(
    client, firestore_db, authenticated_token, monkeypatch
):
    from llink_api.api.routes import history as history_routes

    async def allow(**_kwargs):
        return None

    monkeypatch.setattr(history_routes, "enforce_endpoint_quota", allow)
    own_chats = firestore_db.collection("users").document("phase4-user").collection("chats")
    other_chats = firestore_db.collection("users").document("other-user").collection("chats")
    own_chats.document("same-id").set({"title": "À supprimer"})
    other_chats.document("same-id").set({"title": "À conserver"})

    first = client.delete("/api/history/same-id", headers=authenticated_token)
    second = client.delete("/api/history/same-id", headers=authenticated_token)

    assert first.status_code == 200
    assert first.json()["deleted"] is True
    assert second.status_code == 200
    assert second.json()["deleted"] is False
    assert other_chats.document("same-id").get().exists is True


def test_delete_all_history_only_removes_current_users_chats(
    client, firestore_db, authenticated_token, monkeypatch
):
    from llink_api.api.routes import history as history_routes

    async def allow(**_kwargs):
        return None

    monkeypatch.setattr(history_routes, "enforce_endpoint_quota", allow)
    own = firestore_db.collection("users").document("phase4-user").collection("chats")
    other = firestore_db.collection("users").document("other-user").collection("chats")
    own.document("one").set({"title": "One"})
    own.document("two").set({"title": "Two"})
    other.document("three").set({"title": "Three"})

    response = client.delete("/api/history", headers=authenticated_token)

    assert response.status_code == 200
    assert response.json()["deleted_count"] == 2
    assert list(own.stream()) == []
    assert len(list(other.stream())) == 1


def test_account_deletion_requires_explicit_confirmation(
    client, firestore_db, authenticated_token, no_quota
):
    response = client.request(
        "DELETE",
        "/api/account",
        headers=authenticated_token,
        json={"confirmation": "DELETE"},
    )
    assert response.status_code == 422
    assert firestore_db.collection("users").document("phase4-user").get().exists is False


def test_account_deletion_requires_recent_authentication(
    client, authenticated_token, monkeypatch, no_quota
):
    monkeypatch.setattr(
        security,
        "_decode_firebase_token",
        lambda _token: {"uid": "phase4-user", "auth_time": time.time() - 601},
    )
    response = client.request(
        "DELETE",
        "/api/account",
        headers=authenticated_token,
        json={"confirmation": "SUPPRIMER MON COMPTE"},
    )
    assert response.status_code == 401
    assert "connexion récente" in response.json()["detail"]


def test_account_deletion_purges_firestore_tree_quotas_and_firebase_auth(
    client, firestore_db, authenticated_token, monkeypatch, no_quota
):
    uid = "phase4-user"
    user_ref = firestore_db.collection("users").document(uid)
    user_ref.set({"email": "user@example.test"})
    user_ref.collection("chats").document("chat-1").set({"title": "Private"})
    user_ref.collection("usage_hours").document("hour-1").set({"request_count": 1})
    user_ref.collection("usage_events").document("event-1").set({"cost": 0.01})

    quota_ref = firestore_db.collection("api_rate_limits").document(
        _quota_document_id("uid:" + uid, "chat")
    )
    quota_ref.set({"minute_count": 1})
    deleted_auth_users = []
    monkeypatch.setattr(data_routes.firebase_auth, "delete_user", deleted_auth_users.append)

    response = client.request(
        "DELETE",
        "/api/account",
        headers=authenticated_token,
        json={"confirmation": "SUPPRIMER MON COMPTE"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    assert user_ref.get().exists is False
    assert quota_ref.get().exists is False
    assert deleted_auth_users == [uid]


def test_phase4_quota_defaults_are_bounded():
    assert get_quota_policy("history_delete", True).per_minute == 20
    assert get_quota_policy("history_delete", True).per_day == 100
    assert get_quota_policy("data_export", True).per_day == 10
    assert get_quota_policy("account_delete", True).per_day == 2
    with pytest.raises(RuntimeError):
        get_quota_policy("data_export", False)


def test_delete_method_is_allowed_by_cors_preflight(client):
    response = client.options(
        "/api/history",
        headers={
            "Origin": "https://ll-one-self.vercel.app",
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-methods"]
    assert "DELETE" in response.headers["access-control-allow-methods"]
