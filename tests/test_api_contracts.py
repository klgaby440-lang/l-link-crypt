"""Tests de non-régression des contrats HTTP consommés par le frontend."""

def test_root_health_contract(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Llink Backend API est opérationnel."}


def test_openapi_exposes_stable_request_and_response_schemas(client):
    schema = client.get("/openapi.json").json()
    chat_schema = schema["components"]["schemas"]["ChatPayload"]
    assert set(chat_schema["required"]) == {"message", "model"}
    assert chat_schema["properties"]["data_collection_consent"]["default"] is False
    assert "level" in chat_schema["properties"]
    assert "effort" in chat_schema["properties"]
    assert "history" in chat_schema["properties"]
    assert chat_schema["properties"]["history"]["items"]["$ref"].endswith("/ConversationTurn")
    assert "/api/usage" in schema["paths"]
    assert "/api/history/sync" in schema["paths"]

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


def test_anonymous_user_status_contract(client):
    response = client.get("/api/user/status")
    assert response.status_code == 200
    assert response.json() == {
        "isValid": False,
        "expirationDate": None,
        "isNewUser": False,
    }


def test_chat_rejects_missing_required_fields(client):
    response = client.post("/api/chat", json={})
    assert response.status_code == 422


def test_chat_rejects_unconfigured_provider_before_opening_stream(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    response = client.post(
        "/api/chat",
        json={
            "message": "Bonjour",
            "model": "gemini-1.5-flash",
            "level": "velora",
            "mode": "chat",
        },
    )
    assert response.status_code == 503
    assert "gemini" in response.json()["detail"].lower()


def test_ocr_rejects_non_image_payload(client):
    response = client.post(
        "/api/ocr",
        json={"imageBase64": "data:image/jpeg;base64,aGVsbG8="},
    )
    assert response.status_code == 415
    assert response.json()["detail"]


def test_ocr_returns_safe_provider_error(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # Signature JPEG minimale pour franchir la validation de type/contenu.
    import base64
    jpeg_data_url = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xfftest").decode()
    response = client.post("/api/ocr", json={"imageBase64": jpeg_data_url})
    assert response.status_code == 502
    assert response.json()["detail"] == "Le service de vision est temporairement indisponible."


def test_audio_returns_safe_provider_error(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = client.post(
        "/api/audio",
        files={"file": ("sample.webm", b"audio-bytes", "audio/webm")},
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Le service audio est temporairement indisponible."


def test_audio_rejects_unsupported_content_type(client):
    response = client.post(
        "/api/audio",
        files={"file": ("sample.bin", b"audio-bytes", "application/octet-stream")},
    )
    assert response.status_code == 415


def test_audio_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setenv("MAX_AUDIO_BYTES", "5")
    response = client.post(
        "/api/audio",
        files={"file": ("sample.webm", b"123456", "audio/webm")},
    )
    assert response.status_code == 413


def test_oversized_chat_message_is_rejected(client):
    response = client.post(
        "/api/chat",
        json={"message": "x" * 12_001, "model": "gemini-1.5-flash"},
    )
    assert response.status_code == 422



def test_sync_stream_adapter_accepts_iterable_response_objects():
    import asyncio

    from llink_api.api.routes.chat import _iterate_sync

    class GeminiLikeResponse:
        """Réponse iterable dont l'objet n'est pas directement un itérateur."""

        def __iter__(self):
            return iter(["premier fragment", "deuxième fragment"])

    async def collect():
        return [fragment async for fragment in _iterate_sync(GeminiLikeResponse())]

    assert asyncio.run(collect()) == ["premier fragment", "deuxième fragment"]



def test_usage_route_is_authenticated(client):
    response = client.get("/api/usage")
    assert response.status_code == 401
