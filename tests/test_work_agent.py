"""Tests de l'agent Work natif : appels structurés, boucle et livrables vérifiés."""

import base64
import io

import pytest
from docx import Document

from llink_api.schemas import ChatPayload
from llink_api.services import work_agent
from llink_api.services.model_registry import resolve_model


@pytest.mark.asyncio
async def test_agent_runs_native_tool_calls_in_multiple_rounds_and_verifies_docx(monkeypatch):
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
            document_id = next(
                call["arguments"]["document_id"]
                for message in kwargs["messages"]
                if message.get("role") == "tool"
                for call in []
            ) if False else None
            # The document id is deterministic only through the first tool result.
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
    assert final["reasoning"]["tool_calls"] == 6
    assert any(event["type"] == "tool_result" and event["status"] == "done" for event in events)


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
