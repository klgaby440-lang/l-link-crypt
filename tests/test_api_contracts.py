"""Tests de non-régression des contrats consommés par le frontend actuel."""

def test_root_health_contract(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Llink Backend API est opérationnel."}


def test_openapi_exposes_stable_request_schemas(client):
    schema = client.get("/openapi.json").json()
    chat_schema = schema["components"]["schemas"]["ChatPayload"]
    assert set(chat_schema["required"]) == {"message", "model"}
    assert chat_schema["properties"]["data_collection_consent"]["default"] is False
    assert "/api/history/sync" in schema["paths"]


def test_anonymous_user_status_contract(client):
    response = client.get("/api/user/status")
    assert response.status_code == 200
    assert response.json() == {
        "isValid": False,
        "expirationDate": None,
        "isNewUser": False,
    }


def test_anonymous_history_contract(client):
    response = client.get("/api/history")
    assert response.status_code == 200
    assert response.json() == {"chats": []}


def test_anonymous_history_sync_contract_accepts_legacy_chat_shape(client):
    response = client.post(
        "/api/history/sync",
        json={
            "id": 12,
            "title": "Test",
            "time": 1720000000000,
            "mode": "chat",
            "messages": [{"role": "user", "text": "Bonjour"}],
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "skipped"}


def test_chat_rejects_missing_required_fields(client):
    response = client.post("/api/chat", json={})
    assert response.status_code == 422


def test_chat_keeps_plain_text_stream_contract(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = client.post(
        "/api/chat",
        json={
            "message": "Bonjour",
            "model": "gemini-1.5-flash",
            "mode": "chat",
        },
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "Clé API Gemini manquante" in response.text


def test_ocr_keeps_response_field_when_provider_is_not_configured(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = client.post(
        "/api/ocr",
        json={"imageBase64": "data:image/jpeg;base64,aGVsbG8="},
    )
    assert response.status_code == 200
    assert "response" in response.json()
    assert response.json()["response"].startswith("Erreur Vision :")


def test_audio_keeps_text_field_when_provider_is_not_configured(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = client.post(
        "/api/audio",
        files={"file": ("sample.webm", b"audio-bytes", "audio/webm")},
    )
    assert response.status_code == 200
    assert "text" in response.json()
    assert response.json()["text"].startswith("Erreur Audio :")


def test_response_models_are_registered_in_openapi(client):
    schema = client.get("/openapi.json").json()
    registered = set(schema["components"]["schemas"])
    expected = {
        "HealthResponse",
        "UserStatusResponse",
        "PaymentVerifyResponse",
        "OCRResponse",
        "AudioResponse",
        "HistorySyncResponse",
        "HistoryResponse",
    }
    assert expected.issubset(registered)
