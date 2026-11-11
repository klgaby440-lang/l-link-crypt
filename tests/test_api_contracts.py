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


def test_primeink_course_photo_contract_includes_optional_period_maximum(client):
    schema = client.get("/openapi.json").json()
    route = schema["paths"]["/api/primeink/courses-extract"]["post"]
    course_schema = schema["components"]["schemas"]["PrimeInkExtractedCourseIdentity"]
    properties = course_schema["properties"]

    assert route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/PrimeInkCourseListExtraction"
    )
    assert "maxPer" in properties
    assert properties["maxPer"]["anyOf"][0]["type"] == "number"
    assert properties["maxPer"]["anyOf"][1]["type"] == "null"


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


def test_work_tool_registry_is_discoverable_without_login(client, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)

    response = client.get("/api/work/tools")

    assert response.status_code == 200
    tools = response.json()["tools"]
    assert tools["web_search"] is False
    assert tools["image_search"] is False
    assert tools["image_generate"] is False
    assert tools["python"] is False
    assert tools["exports"] is True
    assert tools["document_create"] is True


def test_work_creates_structured_word_document_without_login(client):
    from io import BytesIO
    from docx import Document

    response = client.post(
        "/api/work/tools/document",
        json={
            "filename": "rapport-test.docx",
            "title": "Rapport de systématique",
            "subtitle": "Famille des Pinaceae",
            "author": "Test Work",
            "institution": "Llink",
            "blocks": [
                {"type": "heading", "level": 1, "text": "Introduction"},
                {"type": "paragraph", "text": "Les Pinaceae sont des conifères."},
                {"type": "table", "rows": [["Genre", "Exemple"], ["Pinus", "Pin sylvestre"]]},
            ],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    document = Document(BytesIO(response.content))
    assert "Rapport de systématique" in [paragraph.text for paragraph in document.paragraphs]
    assert "Introduction" in [paragraph.text for paragraph in document.paragraphs]
    assert len(document.tables) == 1


def test_work_structured_word_rejects_remote_image_urls(client):
    response = client.post(
        "/api/work/tools/document",
        json={
            "filename": "rapport.docx",
            "title": "Document",
            "blocks": [
                {"type": "image", "data_url": "https://example.com/image.png"}
            ],
        },
    )

    assert response.status_code == 422


def test_work_pdf_export_is_available_without_login(client):
    response = client.post(
        "/api/work/exports/pdf",
        json={"filename": "rapport.pdf", "content": "# Rapport\\n\\nTexte de test."},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_work_agent_prompt_describes_general_native_tool_use():
    from llink_api.services.work_agent import TOOLS, _agent_system

    names = [item["function"]["name"] for item in TOOLS]
    instruction = _agent_system("Réponds en français.", names)

    assert "general-purpose tool-using agent" in instruction
    assert "acceptance_criteria" in instruction
    assert "artifact_verify" in instruction
    assert "web_search" in instruction
    assert "image_search" in instruction
    assert "python" in instruction
    assert "document_begin" in instruction
    assert "document_add_blocks" in instruction
    assert "document_finalize" in instruction
    assert "Réponds en français." in instruction


def test_work_native_agent_status_exposes_protocol_and_session_tools(client):
    response = client.get("/api/work/agent/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent"] == "llink-work"
    assert payload["protocol"] == "native_function_calling"
    assert payload["version"] == "native-functions-v1"
    assert payload["limits"]["model_turns"] >= 24
    assert payload["limits"]["tool_calls"] >= 32
    assert {
        "update_plan",
        "web_search",
        "web_open",
        "python",
        "document_begin",
        "document_add_blocks",
        "document_finalize",
        "artifact_verify",
    }.intersection(payload["tools"])

def test_provider_http_rejections_do_not_charge_reserved_credits():
    from llink_api.providers.openai_compatible import ProviderRequestError, TokenUsage
    from llink_api.services.model_registry import resolve_model
    from llink_api.services.usage_meter import settled_cost_microusd

    error = ProviderRequestError("minimax", 402)
    assert error.no_charge is True
    assert error.status_code == 402

    model = resolve_model("noetra")
    assert settled_cost_microusd(
        model=model, usage=None, reserved_cost_microusd=25_000,
        status="provider_rejected",
    ) == 0
    usage = TokenUsage(prompt_tokens=100, completion_tokens=50)
    assert settled_cost_microusd(
        model=model, usage=usage, reserved_cost_microusd=25_000,
        status="provider_rejected",
    ) > 0

