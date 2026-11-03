"""Tests de l'agent Work natif : appels structurés, boucle et livrables vérifiés."""

import asyncio
import base64
import io
import json

import pytest
from docx import Document

from llink_api.schemas import ChatPayload
from llink_api.services import work_agent
from llink_api.services.model_registry import resolve_model


def test_agent_runs_native_tool_calls_in_multiple_rounds_and_verifies_docx(monkeypatch):
    async def run_test():
        async def no_budget(**_kwargs):
            return None

        async def no_settlement(**_kwargs):
            return None

        monkeypatch.setattr(work_agent, "reserve_usage_budget", no_budget)
        monkeypatch.setattr(work_agent, "finalize_usage", no_settlement)

        turns = 0

        async def fake_openai_turn(**kwargs):
            nonlocal turns
            turns += 1
            if turns == 1:
                calls = [
                    {"id": "plan-1", "name": "update_plan", "arguments": {
                        "summary": "Rédiger puis contrôler un document Word.",
                        "steps": [
                            {"label": "Organiser le contenu", "status": "done"},
                            {"label": "Créer et vérifier le DOCX", "status": "in_progress"},
                        ],
                        "decisions": ["Écrire le contenu par sections pour éviter les appels trop volumineux."],
                    }},
                    {"id": "begin-1", "name": "document_begin", "arguments": {
                        "filename": "rapport-agent-test.docx",
                        "title": "Rapport de test agent",
                        "subtitle": "Validation des outils natifs",
                        "author": "Llink Work",
                    }},
                ]
            elif turns == 2:
                prior_tool_turn = next(
                    message for message in kwargs["messages"]
                    if message.get("role") == "assistant" and message.get("tool_calls")
                )
                assert prior_tool_turn.get("reasoning_content") == "Décision intermédiaire conservée pour DeepSeek."
                begin_result = next(
                    message["content"] for message in kwargs["messages"]
                    if message.get("role") == "tool" and message.get("tool_call_id") == "begin-1"
                )
                document_id = json.loads(begin_result)["document_id"]
                calls = [
                    {"id": "blocks-1", "name": "document_add_blocks", "arguments": {
                        "document_id": document_id,
                        "blocks": [
                            {"type": "heading", "level": 1, "text": "Introduction"},
                            {"type": "paragraph", "text": "Un agent doit vérifier ses résultats."},
                            {"type": "table", "rows": [["Étape", "État"], ["Création", "Terminée"]]},
                        ],
                    }},
                    {"id": "finish-1", "name": "document_finalize", "arguments": {"document_id": document_id}},
                ]
            elif turns == 3:
                finish_result = next(
                    message["content"] for message in kwargs["messages"]
                    if message.get("role") == "tool" and message.get("tool_call_id") == "finish-1"
                )
                artifact_id = json.loads(finish_result)["artifact_id"]
                calls = [{"id": "verify-1", "name": "artifact_verify", "arguments": {"artifact_id": artifact_id}}]
            else:
                return "Le document a été créé et vérifié.", [], None, {"role": "assistant", "content": "Le document a été créé et vérifié."}

            assistant_tools = []
            for call in calls:
                assistant_tools.append({
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": json.dumps(call["arguments"])},
                })
            assistant_state = {
                "role": "assistant",
                "content": "",
                "reasoning_content": "Décision intermédiaire conservée pour DeepSeek.",
                "tool_calls": assistant_tools,
            }
            return "", calls, None, assistant_state

        monkeypatch.setattr(work_agent, "_openai_turn", fake_openai_turn)
        events = []

        async def emit(event):
            if event is not None:
                events.append(event)

        payload = ChatPayload(
            message="Crée un document Word et vérifie-le.",
            model="deepseek-flash",
            level="auren",
            effort="normal",
            mode="work",
        )
        await work_agent._run_agent(
            payload=payload,
            request=None,
            user={"uid": "anonymous"},
            db=None,
            model=resolve_model("auren"),
            api_key="test-key",
            base_url="https://provider.example/v1",
            emit=emit,
        )

        final = next(event for event in events if event["type"] == "final")
        assert any(event["type"] == "model_start" for event in events)
        assert any(event["type"] == "model_done" and event["tool_calls"] > 0 for event in events)
        assert turns == 4
        assert final["answer"] == "Le document a été créé et vérifié."
        assert len(final["artifacts"]) == 1
        artifact = final["artifacts"][0]
        assert artifact["filename"] == "rapport-agent-test.docx"
        assert artifact["verification"]["passed"] is True

        data = base64.b64decode(artifact["content_base64"])
        document = Document(io.BytesIO(data))
        assert "Introduction" in [paragraph.text for paragraph in document.paragraphs]
        assert document.tables[0].cell(1, 0).text == "Création"
        assert final["reasoning"]["tool_calls"] == 5
        assert any(event["type"] == "tool_result" and event["status"] == "done" for event in events)


    asyncio.run(run_test())

def test_agent_tool_registry_is_general_and_uses_native_function_schemas():
    names = {item["function"]["name"] for item in work_agent.TOOLS}
    assert {
        "update_plan", "web_search", "web_open", "image_search", "image_generate", "python",
        "document_begin", "document_add_blocks", "document_finalize",
        "artifact_verify", "create_text_file", "export_file",
    }.issubset(names)
    assert all(item["type"] == "function" for item in work_agent.TOOLS)
    assert all("parameters" in item["function"] for item in work_agent.TOOLS)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://127.0.0.1:8000/",
        "http://192.168.1.10/",
        "http://metadata.google.internal/",
    ],
)
def test_web_open_rejects_local_and_non_http_urls(url):
    assert work_agent._host_is_public(url) is False


def test_openai_compatible_native_tool_calls_are_parsed(monkeypatch):
    import asyncio
    import json

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "Le modèle réfléchit à l'appel d'outil.",
                        "tool_calls": [{
                            "id": "call-native-1",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps({"query": "Pinaceae distribution"}),
                            },
                        }],
                    }
                }],
                "usage": {"prompt_tokens": 40, "completion_tokens": 12},
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, json, headers):
            assert url.endswith("/chat/completions")
            assert json["stream"] is False
            assert any(item["function"]["name"] == "web_search" for item in json["tools"])
            return FakeResponse()

    async def run():
        monkeypatch.setattr(work_agent.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
        text, calls, usage, assistant = await work_agent._openai_turn(
            model=resolve_model("auren"),
            base_url="https://provider.example/v1",
            api_key="test",
            system="Work agent",
            messages=[{"role": "user", "content": "Find Pinaceae distribution."}],
            effort="normal",
            timeout_seconds=10,
        )
        assert text == ""
        assert calls == [{
            "id": "call-native-1",
            "name": "web_search",
            "arguments": {"query": "Pinaceae distribution"},
        }]
        assert usage.prompt_tokens == 40
        assert assistant["tool_calls"][0]["id"] == "call-native-1"
        assert assistant["reasoning_content"] == "Le modèle réfléchit à l'appel d'outil."

    asyncio.run(run())


def test_agent_can_embed_a_searched_image_and_verify_it_in_docx():
    import asyncio
    import base64

    from PIL import Image

    async def run():
        output = io.BytesIO()
        Image.new("RGB", (20, 20), (25, 110, 60)).save(output, format="PNG")
        data_url = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
        state = work_agent.AgentState()
        state.images["image-test-1"] = {
            "data_url": data_url,
            "size_bytes": len(output.getvalue()),
            "mime_type": "image/png",
            "description": "Branche de pin",
            "source_url": "https://example.org/pine-photo",
            "source_title": "Photographie botanique",
        }
        user = {"uid": "anonymous"}

        begin = await work_agent._dispatch_tool(
            "document_begin",
            {"filename": "pinaceae-image-test.docx", "title": "Pinaceae illustrées"},
            state=state, request=None, user=user, db=None,
        )
        document_id = begin["document_id"]
        add = await work_agent._dispatch_tool(
            "document_add_blocks",
            {"document_id": document_id, "blocks": [
                {"type": "heading", "level": 1, "text": "Le pin"},
                {"type": "image", "image_id": "image-test-1", "alt": "Aiguilles de pin"},
            ]},
            state=state, request=None, user=user, db=None,
        )
        assert add["total_blocks"] == 3
        assert state.drafts[document_id]["blocks"][1]["data_url"] == data_url
        assert "https://example.org/pine-photo" in state.drafts[document_id]["blocks"][2]["text"]

        built = await work_agent._dispatch_tool(
            "document_finalize", {"document_id": document_id},
            state=state, request=None, user=user, db=None,
        )
        assert built["precheck_passed"] is True
        assert built["status"] == "pending_independent_verification"
        verify = await work_agent._dispatch_tool(
            "artifact_verify", {"artifact_id": built["artifact_id"]},
            state=state, request=None, user=user, db=None,
        )
        assert verify["verified_by_agent"] is True
        raw = state.artifacts[built["artifact_id"]]["data"]
        document = Document(io.BytesIO(raw))
        assert len(document.inline_shapes) == 1

    asyncio.run(run())


def test_artifact_is_not_delivered_without_explicit_independent_verification(monkeypatch):
    import asyncio

    async def no_budget(**_kwargs):
        return None

    async def no_settlement(**_kwargs):
        return None

    async def run():
        monkeypatch.setattr(work_agent, "reserve_usage_budget", no_budget)
        monkeypatch.setattr(work_agent, "finalize_usage", no_settlement)
        state_events = []

        async def fake_openai_turn(**_kwargs):
            return "Le fichier est terminé.", [], None, {"role": "assistant", "content": "Le fichier est terminé."}

        async def emit(event):
            if event is not None:
                state_events.append(event)

        monkeypatch.setattr(work_agent, "_openai_turn", fake_openai_turn)
        payload = ChatPayload(message="Bonjour", model="gemini-1.5-flash", level="velora", mode="work")
        await work_agent._run_agent(
            payload=payload, request=None, user={"uid": "anonymous"}, db=None,
            model=resolve_model("auren"), api_key="test", base_url="https://provider.example/v1",
            emit=emit,
        )
        final = next(event for event in state_events if event["type"] == "final")
        assert final["artifacts"] == []

    asyncio.run(run())


def test_image_search_tool_is_advertised_with_bounded_results():
    image_tool = next(
        item["function"] for item in work_agent.TOOLS
        if item["function"]["name"] == "image_search"
    )
    properties = image_tool["parameters"]["properties"]
    assert properties["max_images"]["maximum"] == 4
    assert properties["query"]["maxLength"] == 400


def test_public_host_resolution_rejects_private_dns(monkeypatch):
    import asyncio
    import socket

    def private_resolution(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    async def run():
        monkeypatch.setattr(work_agent.socket, "getaddrinfo", private_resolution)
        with pytest.raises(ValueError, match="non public"):
            await work_agent._assert_public_host_resolves("https://public.example/resource")

    asyncio.run(run())


def test_available_tool_registry_respects_session_and_server_keys(monkeypatch):
    import os

    monkeypatch.setenv("TAVILY_API_KEY", "tavily-test")
    monkeypatch.setenv("E2B_API_KEY", "e2b-test")
    monkeypatch.setenv("ZAI_API_KEY", "zai-test")
    names = {
        item["function"]["name"]
        for item in work_agent._available_tool_definitions({"uid": "firebase-user"})
    }
    assert {"web_search", "web_open", "image_search", "image_generate", "python"}.issubset(names)
    anonymous_names = {
        item["function"]["name"]
        for item in work_agent._available_tool_definitions({"uid": "anonymous"})
    }
    assert not ({"web_search", "web_open", "image_search", "image_generate", "python"} & anonymous_names)

    monkeypatch.delenv("TAVILY_API_KEY")
    monkeypatch.delenv("E2B_API_KEY")
    monkeypatch.delenv("ZAI_API_KEY")
    limited_names = {
        item["function"]["name"]
        for item in work_agent._available_tool_definitions({"uid": "firebase-user"})
    }
    assert "image_generate" not in limited_names
    assert "image_search" not in limited_names
    assert "python" not in limited_names


def test_glm_image_tool_generates_and_prepares_an_image_artifact(monkeypatch):
    import asyncio
    import base64
    from types import SimpleNamespace

    from PIL import Image

    async def no_quota(**_kwargs):
        return None

    output = io.BytesIO()
    Image.new("RGB", (32, 24), (80, 130, 55)).save(output, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"data": [{"url": "https://images.example/generated.png"}], "content_filter": [{"level": 3}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, headers, json):
            assert url == "https://api.z.ai/api/paas/v4/images/generations"
            assert json["model"] == "glm-image"
            assert json["quality"] == "standard"
            return FakeResponse()

    async def run():
        monkeypatch.setattr(work_agent, "enforce_endpoint_quota", no_quota)
        monkeypatch.setattr(
            work_agent, "get_settings",
            lambda: SimpleNamespace(zai_api_key="zai-test", zai_base_url="https://api.z.ai/api/paas/v4")
        )
        monkeypatch.setattr(work_agent.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
        monkeypatch.setattr(
            work_agent, "_resolve_public_image",
            lambda _url: asyncio.sleep(0, result={
                "data_url": data_url, "size_bytes": len(output.getvalue()), "mime_type": "image/png"
            })
        )
        state = work_agent.AgentState()
        result = await work_agent._dispatch_tool(
            "image_generate",
            {"prompt": "Illustration botanique d'un pin sylvestre isolé", "filename": "pin-sylvestre.png", "size": "1280x1280", "quality": "standard"},
            state=state, request=None, user={"uid": "firebase-user"}, db=None,
        )
        assert result["verified"] is False
        assert result["status"] == "image_ready_pending_independent_verification"
        assert result["image_id"] in state.images
        assert result["artifact_id"] in state.artifacts

        verify = await work_agent._dispatch_tool(
            "artifact_verify", {"artifact_id": result["artifact_id"]},
            state=state, request=None, user={"uid": "firebase-user"}, db=None,
        )
        assert verify["verified_by_agent"] is True
        assert verify["verification"]["format"] == "PNG"

    asyncio.run(run())


def test_docx_quality_gate_checks_word_count_images_tables_sources_and_headings():
    from PIL import Image
    from llink_api.services.document_engine import build_structured_docx

    picture = io.BytesIO()
    Image.new("RGB", (18, 18), (30, 100, 60)).save(picture, format="PNG")
    image_data = "data:image/png;base64," + base64.b64encode(picture.getvalue()).decode("ascii")
    long_text = (
        "Les Pinacées présentent des caractères morphologiques et reproductifs qui varient selon les genres. "
        "Leur étude compare les feuilles, les cônes, les graines, les habitats et les interactions écologiques. "
        "La pollinisation par le vent favorise la dispersion du pollen sur de longues distances. "
        "Les graines peuvent être ailées et sont libérées à maturité par les cônes femelles. "
        "Les espèces occupent des milieux boréaux, tempérés et montagnards, où elles influencent les sols, "
        "les cycles du carbone et les communautés animales. "
    ) * 5
    blocks = [
        {"type": "heading", "level": 1, "text": "Introduction"},
        {"type": "paragraph", "text": long_text + "Source principale : https://example.org/pinaceae"},
        {"type": "heading", "level": 1, "text": "Reproduction"},
        {"type": "image", "data_url": image_data, "alt": "Cône de pin"},
        {"type": "caption", "text": "Figure 1 — Cône de pin"},
        {"type": "table", "rows": [["Genre", "Caractère"], ["Pinus", "Aiguilles en faisceaux"]]},
        {"type": "heading", "level": 1, "text": "Bibliographie"},
        {"type": "paragraph", "text": "Ressource botanique : https://example.org/pinaceae"},
    ]
    raw = build_structured_docx({"title": "Pinaceae", "blocks": blocks})
    checks = work_agent._verify_docx(
        raw,
        blocks,
        {
            "minimum_words": 100,
            "minimum_images": 1,
            "minimum_tables": 1,
            "minimum_source_urls": 1,
            "required_headings": ["Introduction", "Reproduction"],
            "require_bibliography": True,
        },
    )

    assert checks["passed"] is True
    assert checks["word_count"] >= 100
    assert checks["images_found"] == 1
    assert checks["tables_found"] == 1
    assert checks["unique_source_urls"] == 1
    assert checks["bibliography_found"] is True


def test_docx_quality_gate_rejects_incomplete_document():
    from llink_api.services.document_engine import build_structured_docx

    blocks = [
        {"type": "heading", "level": 1, "text": "Introduction"},
        {"type": "paragraph", "text": "Texte trop court."},
    ]
    raw = build_structured_docx({"title": "Document incomplet", "blocks": blocks})
    checks = work_agent._verify_docx(
        raw,
        blocks,
        {
            "minimum_words": 1200,
            "minimum_images": 3,
            "minimum_tables": 2,
            "minimum_source_urls": 4,
            "required_headings": ["Reproduction", "Répartition géographique"],
            "require_bibliography": True,
        },
    )

    assert checks["passed"] is False
    assert checks["minimum_words_met"] is False
    assert checks["minimum_images_met"] is False
    assert checks["minimum_tables_met"] is False
    assert checks["minimum_source_urls_met"] is False
    assert "Reproduction" in checks["missing_required_headings"]
    assert checks["bibliography_required"] is True
    assert checks["bibliography_found"] is False


def test_document_begin_persists_user_quality_contract_and_blocks_failed_delivery():
    async def run():
        state = work_agent.AgentState()
        result = await work_agent._dispatch_tool(
            "document_begin",
            {
                "filename": "rapport-incomplet.docx",
                "title": "Rapport incomplet",
                "quality": {
                    "minimum_words": 1000,
                    "minimum_images": 2,
                    "minimum_tables": 1,
                    "minimum_source_urls": 3,
                    "required_headings": ["Reproduction"],
                    "require_bibliography": True,
                },
            },
            state=state,
            request=None,
            user={"uid": "anonymous"},
            db=None,
        )
        draft = state.drafts[result["document_id"]]
        assert draft["quality"]["minimum_words"] == 1000
        assert draft["quality"]["minimum_images"] == 2
        assert draft["quality"]["required_headings"] == ["Reproduction"]

        await work_agent._dispatch_tool(
            "document_add_blocks",
            {
                "document_id": result["document_id"],
                "blocks": [
                    {"type": "heading", "level": 1, "text": "Introduction"},
                    {"type": "paragraph", "text": "Un paragraphe court."},
                ],
            },
            state=state,
            request=None,
            user={"uid": "anonymous"},
            db=None,
        )
        built = await work_agent._dispatch_tool(
            "document_finalize",
            {"document_id": result["document_id"]},
            state=state,
            request=None,
            user={"uid": "anonymous"},
            db=None,
        )
        assert built["precheck_passed"] is False
        with pytest.raises(ValueError, match="vérification indépendante"):
            await work_agent._dispatch_tool(
                "artifact_verify",
                {"artifact_id": built["artifact_id"]},
                state=state,
                request=None,
                user={"uid": "anonymous"},
                db=None,
            )
        assert state.artifacts[built["artifact_id"]]["verified_by_agent"] is False

    asyncio.run(run())


def test_work_agent_infers_document_requirements_from_the_user_request():
    quality = work_agent._infer_document_quality(
        "Fais des recherches et crée un rapport de 5 pages avec des images et un tableau."
    )

    assert quality["minimum_words"] == 1500
    assert quality["minimum_images"] == 1
    assert quality["minimum_tables"] == 1
    assert quality["minimum_source_urls"] == 3
    assert quality["require_bibliography"] is True
    assert "Bibliographie" in quality["required_headings"]
    assert work_agent._request_requires_artifact(
        "Fais des recherches et crée un rapport de 5 pages."
    ) is True
    assert work_agent._request_requires_artifact(
        "Explique-moi la reproduction des Pinaceae."
    ) is False


def test_document_begin_cannot_lower_inferred_quality_requirements():
    async def run():
        state = work_agent.AgentState(
            user_request="Fais des recherches et crée un rapport de 5 pages avec des images et un tableau."
        )
        result = await work_agent._dispatch_tool(
            "document_begin",
            {
                "filename": "rapport-qualite.docx",
                "title": "Rapport de systématique",
                "quality": {
                    "minimum_words": 100,
                    "minimum_images": 0,
                    "minimum_tables": 0,
                    "minimum_source_urls": 0,
                    "require_bibliography": False,
                },
            },
            state=state,
            request=None,
            user={"uid": "anonymous"},
            db=None,
        )
        quality = state.drafts[result["document_id"]]["quality"]
        assert quality["minimum_words"] == 1500
        assert quality["minimum_images"] == 1
        assert quality["minimum_tables"] == 1
        assert quality["minimum_source_urls"] == 3
        assert quality["require_bibliography"] is True

    asyncio.run(run())


def test_requested_file_is_not_reported_as_delivered_when_no_verified_artifact_exists(monkeypatch):
    async def no_budget(**_kwargs):
        return None

    async def no_settlement(**_kwargs):
        return None

    async def run():
        monkeypatch.setattr(work_agent, "reserve_usage_budget", no_budget)
        monkeypatch.setattr(work_agent, "finalize_usage", no_settlement)
        events = []

        async def fake_openai_turn(**_kwargs):
            return "Le rapport Word est terminé.", [], None, {
                "role": "assistant",
                "content": "Le rapport Word est terminé.",
            }

        async def emit(event):
            if event is not None:
                events.append(event)

        monkeypatch.setattr(work_agent, "_openai_turn", fake_openai_turn)
        payload = ChatPayload(
            message="Crée un rapport Word professionnel et remets le fichier.",
            model="deepseek-flash",
            level="auren",
            mode="work",
        )
        await work_agent._run_agent(
            payload=payload,
            request=None,
            user={"uid": "anonymous"},
            db=None,
            model=resolve_model("auren"),
            api_key="test",
            base_url="https://provider.example/v1",
            emit=emit,
        )
        final = next(event for event in events if event["type"] == "final")
        assert final["artifacts"] == []
        assert "Je n'ai pas remis de fichier" in final["answer"]
        assert final["reasoning"]["status"] == "completed_with_limitations"
        assert any("aucun fichier vérifié" in item for item in final["reasoning"]["limitations"])

    asyncio.run(run())
