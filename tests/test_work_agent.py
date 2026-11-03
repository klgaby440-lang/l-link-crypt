"""Tests de l'agent Work natif : appels structurés, boucle et livrables vérifiés."""

import asyncio
import base64
import io

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
                begin_result = next(
                    message["content"] for message in kwargs["messages"]
                    if message.get("role") == "tool" and message.get("tool_call_id") == "begin-1"
                )
                import json
                document_id = json.loads(begin_result)["result"]["document_id"]
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
                import json
                finish_result = next(
                    message["content"] for message in kwargs["messages"]
                    if message.get("role") == "tool" and message.get("tool_call_id") == "finish-1"
                )
                artifact_id = json.loads(finish_result)["result"]["artifact_id"]
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
            assistant_state = {"role": "assistant", "content": "", "tool_calls": assistant_tools}
            return "", calls, None, assistant_state

        monkeypatch.setattr(work_agent, "_openai_turn", fake_openai_turn)
        events = []

        async def emit(event):
            if event is not None:
                events.append(event)

        payload = ChatPayload(
            message="Crée un document Word et vérifie-le.",
            model="gemini-1.5-flash",
            level="velora",
            effort="normal",
            mode="work",
        )
        await work_agent._run_agent(
            payload=payload,
            request=None,
            user={"uid": "anonymous"},
            db=None,
            model=resolve_model("velora"),
            api_key="test-key",
            base_url="https://provider.example/v1",
            emit=emit,
        )

        final = next(event for event in events if event["type"] == "final")
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
        "update_plan", "web_search", "web_open", "python",
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
        assert built["verified"] is True
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
            model=resolve_model("velora"), api_key="test", base_url="https://provider.example/v1",
            emit=emit,
        )
        final = next(event for event in state_events if event["type"] == "final")
        assert final["artifacts"] == []

    asyncio.run(run())
