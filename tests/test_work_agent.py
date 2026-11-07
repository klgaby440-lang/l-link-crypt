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
                    {"id": "doc-plan-1", "name": "document_plan", "arguments": {
                        "title": "Rapport de test agent",
                        "target_total_words": 100,
                        "sections": [
                            {"id": "intro", "title": "Introduction", "purpose": "Présenter le sujet et les objectifs du rapport.", "target_words": 34},
                            {"id": "method", "title": "Méthode", "purpose": "Expliquer les étapes et les critères utilisés.", "target_words": 33},
                            {"id": "conclusion", "title": "Conclusion", "purpose": "Résumer les résultats et les suites possibles.", "target_words": 33},
                        ],
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
                    {"id": "blocks-intro", "name": "document_add_blocks", "arguments": {
                        "document_id": document_id, "section_id": "intro", "section_complete": True,
                        "blocks": [
                            {"type": "heading", "level": 1, "text": "Introduction"},
                            {"type": "paragraph", "text": "Un agent doit vérifier ses résultats et organiser les informations avant de créer un livrable. Une introduction claire présente le sujet, explique les objectifs et annonce la progression du document."},
                            {"type": "table", "rows": [["Étape", "État"], ["Création", "Terminée"]]},
                        ],
                    }},
                    {"id": "blocks-method", "name": "document_add_blocks", "arguments": {
                        "document_id": document_id, "section_id": "method", "section_complete": True,
                        "blocks": [
                            {"type": "heading", "level": 1, "text": "Méthode"},
                            {"type": "paragraph", "text": "La méthode consiste à répartir le travail en parties cohérentes. Chaque partie est rédigée séparément, puis les contrôles relisent le document final afin de repérer les oublis et les erreurs de structure."},
                        ],
                    }},
                    {"id": "blocks-conclusion", "name": "document_add_blocks", "arguments": {
                        "document_id": document_id, "section_id": "conclusion", "section_complete": True,
                        "blocks": [
                            {"type": "heading", "level": 1, "text": "Conclusion"},
                            {"type": "paragraph", "text": "Cette organisation rend la rédaction plus lisible et plus fiable. Elle permet aussi de corriger une partie sans recommencer tout le document, avant de produire et vérifier le fichier Word définitif."},
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
        assert final["reasoning"]["tool_calls"] == 8
        assert any(event["type"] == "tool_result" and event["status"] == "done" for event in events)
        progress = [event for event in events if event["type"] == "document_progress"]
        assert len(progress) == 4
        assert progress[0]["document"]["blocks"] == []
        assert progress[0]["document"]["filename"] == "rapport-agent-test.docx"
        assert [item["title"] for item in progress[0]["document"]["outline"]] == ["Introduction", "Méthode", "Conclusion"]
        assert progress[-1]["document"]["revision_count"] == 3
        assert progress[-1]["document"]["blocks"][0]["text"] == "Introduction"
        assert progress[-1]["document"]["blocks"][1]["text"].startswith("Un agent doit vérifier ses résultats")


    asyncio.run(run_test())

def test_agent_tool_registry_is_general_and_uses_native_function_schemas():
    names = {item["function"]["name"] for item in work_agent.TOOLS}
    assert {
        "update_plan", "web_search", "web_open", "image_search", "image_generate", "image_edit", "python",
        "document_plan", "document_begin", "document_add_blocks", "document_finalize",
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



def test_workspace_tools_are_native_and_are_only_advertised_to_authenticated_users(monkeypatch):
    from types import SimpleNamespace

    expected = {
        "workspace_list_projects", "workspace_list_files", "workspace_read_file",
        "workspace_search_files", "workspace_create_project",
        "workspace_create_file", "workspace_update_file",
    }
    names = {item["function"]["name"] for item in work_agent.TOOLS}
    assert expected.issubset(names)
    assert all("parameters" in item["function"] for item in work_agent.TOOLS
               if item["function"]["name"] in expected)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        work_agent,
        "get_settings",
        lambda: SimpleNamespace(gemini_api_key="", zai_api_key=""),
    )
    authenticated = {item["function"]["name"] for item in work_agent._available_tool_definitions({"uid": "work-user"})}
    anonymous = {item["function"]["name"] for item in work_agent._available_tool_definitions({"uid": "anonymous"})}
    assert expected.issubset(authenticated)
    assert not (expected & anonymous)


def test_image_generation_is_advertised_to_authenticated_users_without_subscription_gate(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        work_agent,
        "get_settings",
        lambda: SimpleNamespace(gemini_api_key="gemini-test", zai_api_key=""),
    )
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("E2B_API_KEY", raising=False)

    authenticated = {
        item["function"]["name"]
        for item in work_agent._available_tool_definitions({"uid": "student-account"})
    }
    anonymous = {
        item["function"]["name"]
        for item in work_agent._available_tool_definitions({"uid": "anonymous"})
    }

    # L'outil est exposé à tout compte authentifié dès que Gemini est configuré.
    # Le registre ne reçoit aucune formule d'abonnement et ne filtre pas cet outil par plan.
    assert "image_generate" in authenticated
    assert "image_edit" in authenticated
    assert "image_generate" not in anonymous
    assert "image_edit" not in anonymous


def test_workspace_dispatch_creates_reads_and_updates_real_workspace_files(monkeypatch):
    from llink_api.api.routes import work as work_routes

    store = {
        "id": "a" * 32, "name": "main.py", "folder": "src", "path": "src/main.py",
        "language": "python", "project_id": None, "content": "print('hello')",
        "size_bytes": 14, "version": 1, "updated_at": "2026-11-03T12:00:00Z",
    }

    async def fake_create_file(payload, request, user, db):
        store.update({"name": payload.name, "folder": payload.folder,
                      "path": (payload.folder + "/" if payload.folder else "") + payload.name,
                      "language": payload.language, "content": payload.content,
                      "size_bytes": len(payload.content.encode("utf-8")),
                      "project_id": payload.project_id, "version": 1})
        return {"id": store["id"], **store}

    async def fake_get_file(file_id, request, user, db):
        assert file_id == store["id"]
        return dict(store)

    async def fake_update_file(file_id, payload, request, user, db):
        assert payload.expected_version == store["version"]
        store.update({"content": payload.content, "size_bytes": len(payload.content.encode("utf-8")),
                      "version": store["version"] + 1})
        if payload.name is not None:
            store["name"] = payload.name
        if payload.folder is not None:
            store["folder"] = payload.folder
        store["path"] = (store["folder"] + "/" if store["folder"] else "") + store["name"]
        if payload.language is not None:
            store["language"] = payload.language
        return {"id": store["id"], **store}

    monkeypatch.setattr(work_routes, "create_file", fake_create_file)
    monkeypatch.setattr(work_routes, "get_file", fake_get_file)
    monkeypatch.setattr(work_routes, "update_file", fake_update_file)

    async def run():
        state = work_agent.AgentState(user_request="Crée et modifie un fichier Python dans Work.")
        user = {"uid": "work-user"}
        created = await work_agent._dispatch_tool(
            "workspace_create_file",
            {"path": "src/main.py", "content": "print('hello')", "language": "python"},
            state=state, request=None, user=user, db=object(),
        )
        assert created["saved"] is True
        assert created["file_id"] == "a" * 32
        assert state.workspace_changes["a" * 32]["content"] == "print('hello')"

        read = await work_agent._dispatch_tool(
            "workspace_read_file", {"file_id": "a" * 32},
            state=state, request=None, user=user, db=object(),
        )
        assert read["version"] == 1
        assert "print('hello')" in read["content"]

        updated = await work_agent._dispatch_tool(
            "workspace_update_file",
            {"file_id": "a" * 32, "expected_version": 1, "content": "print('hello world')"},
            state=state, request=None, user=user, db=object(),
        )
        assert updated["saved"] is True
        assert updated["version"] == 2
        assert state.workspace_changes["a" * 32]["content"] == "print('hello world')"

        with pytest.raises(PermissionError):
            await work_agent._dispatch_tool("workspace_list_projects", {}, state=state,
                                            request=None, user={"uid": "anonymous"}, db=None)

    asyncio.run(run())


def test_academic_document_requests_require_substantial_content_and_sources():
    quality = work_agent._infer_document_quality(
        "Prépare un travail pratique de systématique sur les Pinaceae."
    )
    assert quality["minimum_words"] >= 900
    assert quality["minimum_source_urls"] >= 3
    assert quality["require_bibliography"] is True
    assert "Bibliographie" in quality["required_headings"]



def test_document_begin_resumes_unverified_draft_instead_of_starting_over():
    async def run():
        state = work_agent.AgentState()
        first = await work_agent._dispatch_tool(
            "document_begin",
            {"filename": "cycle-krebs.docx", "title": "Cycle de Krebs", "quality": {"minimum_words": 50}},
            state=state, request=None, user={"uid": "anonymous"}, db=None,
        )
        await work_agent._dispatch_tool(
            "document_add_blocks",
            {"document_id": first["document_id"], "blocks": [
                {"type": "heading", "level": 1, "text": "Introduction"},
                {"type": "paragraph", "text": "Texte trop court."},
            ]},
            state=state, request=None, user={"uid": "anonymous"}, db=None,
        )
        failed = await work_agent._dispatch_tool(
            "document_finalize", {"document_id": first["document_id"]},
            state=state, request=None, user={"uid": "anonymous"}, db=None,
        )
        assert failed["precheck_passed"] is False
        resumed = await work_agent._dispatch_tool(
            "document_begin",
            {"filename": "cycle-krebs.docx", "title": "Cycle de Krebs"},
            state=state, request=None, user={"uid": "anonymous"}, db=None,
        )
        assert resumed["status"] == "existing_draft_resumed"
        assert resumed["document_id"] == first["document_id"]
        assert resumed["existing_blocks"] == 2
        restarted = await work_agent._dispatch_tool(
            "document_begin",
            {"filename": "cycle-krebs.docx", "title": "Cycle de Krebs", "restart": True},
            state=state, request=None, user={"uid": "anonymous"}, db=None,
        )
        assert restarted["document_id"] != first["document_id"]

    asyncio.run(run())


def test_document_outline_enforces_order_and_requires_every_section_before_finalize():
    async def run():
        state = work_agent.AgentState(user_request="Crée un document Word détaillé.")
        user = {"uid": "anonymous"}
        with pytest.raises(ValueError, match="document_plan"):
            await work_agent._dispatch_tool(
                "document_begin", {"filename": "sections.docx", "title": "Sections"},
                state=state, request=None, user=user, db=None,
            )

        planned = await work_agent._dispatch_tool(
            "document_plan",
            {
                "title": "Rapport structuré",
                "target_total_words": 100,
                "sections": [
                    {"id": "intro", "title": "Introduction", "purpose": "Présenter le sujet et les objectifs.", "target_words": 30},
                    {"id": "analysis", "title": "Analyse", "purpose": "Développer les éléments principaux du sujet.", "target_words": 30},
                    {"id": "conclusion", "title": "Conclusion", "purpose": "Résumer les résultats et les limites.", "target_words": 30},
                ],
            },
            state=state, request=None, user=user, db=None,
        )
        assert planned["sections_count"] == 3

        begin = await work_agent._dispatch_tool(
            "document_begin",
            {"filename": "sections.docx", "title": "Rapport structuré"},
            state=state, request=None, user=user, db=None,
        )
        document_id = begin["document_id"]

        first_batch = await work_agent._dispatch_tool(
            "document_add_blocks",
            {
                "document_id": document_id, "section_id": "intro", "section_complete": False,
                "blocks": [
                    {"type": "heading", "level": 1, "text": "Introduction"},
                    {"type": "paragraph", "text": "Cette première partie présente le sujet, précise les objectifs du rapport et annonce les thèmes qui seront étudiés. Elle fournit au lecteur les repères nécessaires pour comprendre la suite."},
                ],
            },
            state=state, request=None, user=user, db=None,
        )
        assert first_batch["section"]["status"] == "in_progress"
        with pytest.raises(ValueError, match="[Oo]rdre des sections"):
            await work_agent._dispatch_tool(
                "document_add_blocks",
                {"document_id": document_id, "section_id": "analysis", "section_complete": True,
                 "blocks": [{"type": "heading", "level": 1, "text": "Analyse"}]},
                state=state, request=None, user=user, db=None,
            )
        with pytest.raises(ValueError, match="Finalisation prématurée"):
            await work_agent._dispatch_tool(
                "document_finalize", {"document_id": document_id},
                state=state, request=None, user=user, db=None,
            )

        await work_agent._dispatch_tool(
            "document_add_blocks",
            {"document_id": document_id, "section_id": "intro", "section_complete": True,
             "blocks": [{"type": "paragraph", "text": "Cette seconde livraison clôt l'introduction et prépare la transition vers l'analyse approfondie du sujet."}]},
            state=state, request=None, user=user, db=None,
        )
        await work_agent._dispatch_tool(
            "document_add_blocks",
            {"document_id": document_id, "section_id": "analysis", "section_complete": True,
             "blocks": [
                 {"type": "heading", "level": 1, "text": "Analyse"},
                 {"type": "paragraph", "text": "L'analyse examine les informations utiles, compare les éléments disponibles et explique leurs relations. Chaque affirmation importante doit être justifiée par des faits pertinents et replacée dans son contexte."},
             ]},
            state=state, request=None, user=user, db=None,
        )
        await work_agent._dispatch_tool(
            "document_add_blocks",
            {"document_id": document_id, "section_id": "conclusion", "section_complete": True,
             "blocks": [
                 {"type": "heading", "level": 1, "text": "Conclusion"},
                 {"type": "paragraph", "text": "La conclusion rassemble les résultats, rappelle les limites de l'étude et propose des pistes cohérentes pour approfondir le sujet. Elle termine le rapport sans introduire de nouveaux arguments non démontrés."},
             ]},
            state=state, request=None, user=user, db=None,
        )
        finalized = await work_agent._dispatch_tool(
            "document_finalize", {"document_id": document_id},
            state=state, request=None, user=user, db=None,
        )
        assert finalized["precheck_passed"] is True
        assert all(section["status"] == "completed" for section in state.drafts[document_id]["outline"])
        verified = await work_agent._dispatch_tool(
            "artifact_verify", {"artifact_id": finalized["artifact_id"]},
            state=state, request=None, user=user, db=None,
        )
        assert verified["verified"] is True

    asyncio.run(run())


def test_failed_docx_quality_gate_opens_same_draft_repair_section_and_can_pass():
    async def run():
        state = work_agent.AgentState(user_request="Crée un rapport Word structuré.")
        user = {"uid": "anonymous"}
        await work_agent._dispatch_tool(
            "document_plan",
            {
                "title": "Rapport avec correction",
                "target_total_words": 100,
                "sections": [
                    {"id": "intro", "title": "Introduction", "purpose": "Présenter le sujet et ses objectifs.", "target_words": 30},
                    {"id": "analysis", "title": "Analyse", "purpose": "Développer les informations principales.", "target_words": 30},
                    {"id": "conclusion", "title": "Conclusion", "purpose": "Résumer les résultats essentiels.", "target_words": 30},
                ],
            },
            state=state, request=None, user=user, db=None,
        )
        begin = await work_agent._dispatch_tool(
            "document_begin",
            {"filename": "rapport-reparation.docx", "title": "Rapport avec correction"},
            state=state, request=None, user=user, db=None,
        )
        document_id = begin["document_id"]
        for section_id, title, body in [
            ("intro", "Introduction", "Cette introduction présente brièvement le sujet et ses objectifs."),
            ("analysis", "Analyse", "L'analyse expose les éléments essentiels et leurs relations."),
            ("conclusion", "Conclusion", "La conclusion résume les observations principales."),
        ]:
            await work_agent._dispatch_tool(
                "document_add_blocks",
                {"document_id": document_id, "section_id": section_id, "section_complete": True,
                 "blocks": [
                     {"type": "heading", "level": 1, "text": title},
                     {"type": "paragraph", "text": body},
                 ]},
                state=state, request=None, user=user, db=None,
            )

        first = await work_agent._dispatch_tool(
            "document_finalize", {"document_id": document_id},
            state=state, request=None, user=user, db=None,
        )
        assert first["precheck_passed"] is False
        assert first["repair_section_id"] == "quality-repair"
        assert state.drafts[document_id]["current_section_index"] == 3

        detailed_repair = (
            "Cette partie apporte les compléments nécessaires au rapport. Elle précise le contexte, définit les notions "
            "utilisées et explique les principales relations entre les éléments étudiés. Elle développe les conséquences "
            "pratiques, distingue les faits établis des interprétations et rappelle les limites des informations disponibles. "
            "Les exemples permettent d'illustrer les idées sans répéter les paragraphes précédents. Les critères de qualité "
            "sont repris un par un afin de s'assurer que le contenu est suffisamment complet, clair, cohérent et utile au lecteur. "
            "Cette correction renforce aussi les transitions entre les sections et fournit une synthèse plus approfondie du sujet. "
        ) * 3
        await work_agent._dispatch_tool(
            "document_add_blocks",
            {"document_id": document_id, "section_id": "quality-repair", "section_complete": True,
             "blocks": [
                 {"type": "heading", "level": 1, "text": "Compléments et corrections"},
                 {"type": "paragraph", "text": detailed_repair},
             ]},
            state=state, request=None, user=user, db=None,
        )
        second = await work_agent._dispatch_tool(
            "document_finalize", {"document_id": document_id},
            state=state, request=None, user=user, db=None,
        )
        assert second["precheck_passed"] is True
        verified = await work_agent._dispatch_tool(
            "artifact_verify", {"artifact_id": second["artifact_id"]},
            state=state, request=None, user=user, db=None,
        )
        assert verified["verified"] is True
        assert verified["draft_id"] == document_id

    asyncio.run(run())


def test_docx_artifact_from_an_older_revision_cannot_be_verified():
    async def run():
        state = work_agent.AgentState()
        begin = await work_agent._dispatch_tool(
            "document_begin",
            {"filename": "revision.docx", "title": "Contrôle des révisions", "quality": {"minimum_words": 5}},
            state=state, request=None, user={"uid": "anonymous"}, db=None,
        )
        document_id = begin["document_id"]
        await work_agent._dispatch_tool(
            "document_add_blocks",
            {"document_id": document_id, "blocks": [
                {"type": "heading", "level": 1, "text": "Première version"},
                {"type": "paragraph", "text": "Un premier contenu suffisamment clair est présent dans le document initial."},
            ]},
            state=state, request=None, user={"uid": "anonymous"}, db=None,
        )
        first = await work_agent._dispatch_tool(
            "document_finalize", {"document_id": document_id},
            state=state, request=None, user={"uid": "anonymous"}, db=None,
        )
        assert first["precheck_passed"] is True

        await work_agent._dispatch_tool(
            "document_add_blocks",
            {"document_id": document_id, "blocks": [
                {"type": "paragraph", "text": "Une modification ultérieure change le contenu et invalide nécessairement le fichier Word déjà construit."},
            ]},
            state=state, request=None, user={"uid": "anonymous"}, db=None,
        )
        stale = await work_agent._dispatch_tool(
            "artifact_verify", {"artifact_id": first["artifact_id"]},
            state=state, request=None, user={"uid": "anonymous"}, db=None,
        )
        assert stale["verified"] is False
        assert stale["stale"] is True

        second = await work_agent._dispatch_tool(
            "document_finalize", {"document_id": document_id},
            state=state, request=None, user={"uid": "anonymous"}, db=None,
        )
        verified = await work_agent._dispatch_tool(
            "artifact_verify", {"artifact_id": second["artifact_id"]},
            state=state, request=None, user={"uid": "anonymous"}, db=None,
        )
        assert verified["verified"] is True

    asyncio.run(run())


def test_project_sandbox_tools_require_e2b_and_are_not_advertised_to_anonymous(monkeypatch):
    sandbox_tools = {
        "project_sandbox_open", "project_run", "project_list_files",
        "project_read_file", "project_sync_files",
    }
    monkeypatch.setenv("E2B_API_KEY", "sandbox-test")
    authenticated = {
        item["function"]["name"]
        for item in work_agent._available_tool_definitions({"uid": "work-user"})
    }
    anonymous = {
        item["function"]["name"]
        for item in work_agent._available_tool_definitions({"uid": "anonymous"})
    }
    assert sandbox_tools.issubset(authenticated)
    assert not (sandbox_tools & anonymous)
    monkeypatch.delenv("E2B_API_KEY")
    without_key = {
        item["function"]["name"]
        for item in work_agent._available_tool_definitions({"uid": "work-user"})
    }
    assert not (sandbox_tools & without_key)


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
    from types import SimpleNamespace

    monkeypatch.setattr(
        work_agent,
        "get_settings",
        lambda: SimpleNamespace(gemini_api_key="gemini-test"),
    )
    monkeypatch.setenv("E2B_API_KEY", "e2b-test")
    names = {
        item["function"]["name"]
        for item in work_agent._available_tool_definitions({"uid": "firebase-user"})
    }
    expected = {"web_search", "web_open", "image_search", "image_generate", "image_edit", "python"}
    assert expected.issubset(names)

    anonymous_names = {
        item["function"]["name"]
        for item in work_agent._available_tool_definitions({"uid": "anonymous"})
    }
    assert not (expected & anonymous_names)

    monkeypatch.setattr(
        work_agent,
        "get_settings",
        lambda: SimpleNamespace(gemini_api_key=""),
    )
    monkeypatch.delenv("E2B_API_KEY")
    limited_names = {
        item["function"]["name"]
        for item in work_agent._available_tool_definitions({"uid": "firebase-user"})
    }
    assert not ({"web_search", "image_search", "image_generate", "image_edit", "python"} & limited_names)


def test_gemini_image_tools_generate_and_edit_verified_artifacts(monkeypatch):
    import base64
    from types import SimpleNamespace

    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (32, 24), (80, 130, 55)).save(output, format="PNG")
    png_bytes = output.getvalue()
    encoded_image = base64.b64encode(png_bytes).decode("ascii")
    source_image = {"filename": "source.png", "mime_type": "image/png", "data": png_bytes}
    seen_requests = []

    async def no_quota(**_kwargs):
        return None

    async def fake_generate_content(prompt, **kwargs):
        seen_requests.append({"prompt": prompt, **kwargs})
        assert kwargs["model"] == "gemini-3.1-flash-image"
        return {
            "content": {
                "parts": [{
                    "inlineData": {
                        "mimeType": "image/png",
                        "data": encoded_image,
                    }
                }]
            }
        }

    async def run():
        monkeypatch.setattr(work_agent, "enforce_endpoint_quota", no_quota)
        monkeypatch.setattr(
            work_agent,
            "get_settings",
            lambda: SimpleNamespace(gemini_api_key="gemini-test"),
        )
        monkeypatch.setattr(work_agent, "_gemini_generate_content", fake_generate_content)

        generated_state = work_agent.AgentState()
        generated = await work_agent._dispatch_tool(
            "image_generate",
            {
                "prompt": "Illustration botanique d'un pin sylvestre isolé",
                "filename": "pin-sylvestre.png",
                "aspect_ratio": "1:1",
                "quality": "standard",
            },
            state=generated_state, request=None, user={"uid": "firebase-user"}, db=None,
        )
        assert generated["verified"] is False
        assert generated["status"] == "image_ready_pending_independent_verification"
        assert generated["image_id"] in generated_state.images
        assert generated["artifact_id"] in generated_state.artifacts
        assert seen_requests[-1]["image_inputs"] == []

        verified_generation = await work_agent._dispatch_tool(
            "artifact_verify", {"artifact_id": generated["artifact_id"]},
            state=generated_state, request=None, user={"uid": "firebase-user"}, db=None,
        )
        assert verified_generation["verified_by_agent"] is True
        assert verified_generation["verification"]["format"] == "PNG"

        edit_state = work_agent.AgentState(input_images=[source_image])
        edited = await work_agent._dispatch_tool(
            "image_edit",
            {
                "prompt": "Remplace le fond par un arrière-plan naturel vert doux.",
                "filename": "pin-retouche.png",
                "source_index": 0,
                "aspect_ratio": "1:1",
                "quality": "standard",
            },
            state=edit_state, request=None, user={"uid": "firebase-user"}, db=None,
        )
        assert edited["source_image_index"] == 0
        assert seen_requests[-1]["image_inputs"][0]["data"] == png_bytes
        assert "MODIFICATION D'IMAGE" in seen_requests[-1]["prompt"]

        verified_edit = await work_agent._dispatch_tool(
            "artifact_verify", {"artifact_id": edited["artifact_id"]},
            state=edit_state, request=None, user={"uid": "firebase-user"}, db=None,
        )
        assert verified_edit["verified_by_agent"] is True
        assert verified_edit["verification"]["format"] == "PNG"

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
        failed_verify = await work_agent._dispatch_tool(
            "artifact_verify",
            {"artifact_id": built["artifact_id"]},
            state=state,
            request=None,
            user={"uid": "anonymous"},
            db=None,
        )
        assert failed_verify["verified"] is False
        assert failed_verify["draft_id"] == result["document_id"]
        assert failed_verify["repair_guidance"]
        assert "Ne livre pas ce fichier" in failed_verify["next_action"]
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

    course = work_agent._infer_document_quality(
        "Étoffe ce document pour créer un cours complet de biochimie détaillé sur le Cycle de Krebs au format Word."
    )
    assert course["minimum_words"] >= 1500
    assert course["minimum_source_urls"] >= 3
    assert course["minimum_tables"] >= 1
    assert course["require_bibliography"] is True
    assert "Étapes enzymatiques" in course["required_headings"]
    assert "Rôle amphibolique" in course["required_headings"]


def test_document_begin_cannot_lower_inferred_quality_requirements():
    async def run():
        state = work_agent.AgentState(
            user_request="Fais des recherches et crée un rapport de 5 pages avec des images et un tableau."
        )
        await work_agent._dispatch_tool(
            "document_plan",
            {
                "title": "Rapport de systématique",
                "target_total_words": 1500,
                "sections": [
                    {"id": "intro", "title": "Introduction", "purpose": "Présenter le contexte et les objectifs du rapport.", "target_words": 500},
                    {"id": "analysis", "title": "Analyse", "purpose": "Développer les éléments scientifiques principaux.", "target_words": 500},
                    {"id": "conclusion", "title": "Conclusion", "purpose": "Résumer les résultats et les limites du rapport.", "target_words": 500},
                ],
            },
            state=state, request=None, user={"uid": "anonymous"}, db=None,
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


def test_corrected_docx_supersedes_failed_version_and_can_be_delivered():
    async def run():
        state = work_agent.AgentState()
        begin = await work_agent._dispatch_tool(
            "document_begin",
            {
                "filename": "rapport-corrige.docx",
                "title": "Rapport corrigé",
                "quality": {"minimum_words": 20},
            },
            state=state,
            request=None,
            user={"uid": "anonymous"},
            db=None,
        )
        document_id = begin["document_id"]
        await work_agent._dispatch_tool(
            "document_add_blocks",
            {
                "document_id": document_id,
                "blocks": [
                    {"type": "heading", "level": 1, "text": "Introduction"},
                    {"type": "paragraph", "text": "Texte initial trop court."},
                ],
            },
            state=state,
            request=None,
            user={"uid": "anonymous"},
            db=None,
        )
        first = await work_agent._dispatch_tool(
            "document_finalize",
            {"document_id": document_id},
            state=state,
            request=None,
            user={"uid": "anonymous"},
            db=None,
        )
        assert first["precheck_passed"] is False

        await work_agent._dispatch_tool(
            "document_add_blocks",
            {
                "document_id": document_id,
                "blocks": [
                    {"type": "paragraph", "text": "Ce paragraphe supplémentaire apporte assez de contenu pour atteindre le minimum de mots exigé par le contrat de qualité."}
                ],
            },
            state=state,
            request=None,
            user={"uid": "anonymous"},
            db=None,
        )
        second = await work_agent._dispatch_tool(
            "document_finalize",
            {"document_id": document_id},
            state=state,
            request=None,
            user={"uid": "anonymous"},
            db=None,
        )
        assert second["precheck_passed"] is True
        # The previous failed artifact stays active until independent verification succeeds.
        assert state.artifacts[first["artifact_id"]]["superseded"] is False
        assert state.artifacts[second["artifact_id"]]["superseded"] is False

        verified = await work_agent._dispatch_tool(
            "artifact_verify",
            {"artifact_id": second["artifact_id"]},
            state=state,
            request=None,
            user={"uid": "anonymous"},
            db=None,
        )
        assert verified["verified"] is True
        assert state.artifacts[second["artifact_id"]]["verified_by_agent"] is True

        active_artifacts = [
            artifact for artifact in state.artifacts.values()
            if not artifact.get("superseded")
        ]
        assert [artifact["artifact_id"] for artifact in active_artifacts] == [second["artifact_id"]]

    asyncio.run(run())


def test_gemini_parallel_function_results_are_batched_in_order_with_ids(monkeypatch):
    import asyncio
    from google.genai import types

    async def no_budget(**_kwargs):
        return None

    async def no_settlement(**_kwargs):
        return None

    async def run():
        monkeypatch.setattr(work_agent, "reserve_usage_budget", no_budget)
        monkeypatch.setattr(work_agent, "finalize_usage", no_settlement)
        turns = 0

        async def fake_gemini_turn(**kwargs):
            nonlocal turns
            turns += 1
            if turns == 1:
                calls = [
                    {
                        "id": "gemini-id-1",
                        "native_id": "gemini-id-1",
                        "name": "update_plan",
                        "arguments": {
                            "summary": "Première mise à jour.",
                            "steps": [{"label": "Étape A", "status": "done"}],
                        },
                    },
                    {
                        "id": "gemini-id-2",
                        "native_id": "gemini-id-2",
                        "name": "update_plan",
                        "arguments": {
                            "summary": "Deuxième mise à jour.",
                            "steps": [{"label": "Étape B", "status": "done"}],
                        },
                    },
                ]
                assistant_state = types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name=call["name"],
                                args=call["arguments"],
                                id=call["native_id"],
                            )
                        )
                        for call in calls
                    ],
                )
                return "", calls, None, assistant_state

            response_content = kwargs["contents"][-1]
            assert response_content.role == "user"
            assert len(response_content.parts) == 2
            responses = [part.function_response for part in response_content.parts]
            assert [item.name for item in responses] == ["update_plan", "update_plan"]
            assert [item.id for item in responses] == ["gemini-id-1", "gemini-id-2"]
            return "Les deux actions ont été exécutées.", [], None, None

        monkeypatch.setattr(work_agent, "_gemini_turn", fake_gemini_turn)
        events = []

        async def emit(event):
            if event is not None:
                events.append(event)

        payload = ChatPayload(
            message="Prépare un court plan.",
            model="gemini-3.5-flash-lite",
            level="velora",
            mode="work",
        )
        await work_agent._run_agent(
            payload=payload,
            request=None,
            user={"uid": "anonymous"},
            db=None,
            model=resolve_model("velora"),
            api_key="test-gemini-key",
            base_url="",
            emit=emit,
        )

        final = next(event for event in events if event["type"] == "final")
        assert final["answer"] == "Les deux actions ont été exécutées."
        assert final["reasoning"]["tool_calls"] == 2
        assert turns == 2

    asyncio.run(run())


def test_gemini_turn_preserves_native_function_call_ids(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from google.genai import types

    function_content = types.Content(
        role="model",
        parts=[
            types.Part(
                function_call=types.FunctionCall(
                    name="web_search",
                    args={"query": "Pinaceae"},
                    id="native-google-call-42",
                )
            )
        ],
    )
    fake_response = SimpleNamespace(
        candidates=[SimpleNamespace(content=function_content)],
        usage_metadata=None,
        text="",
    )

    class FakeModels:
        def generate_content(self, **_kwargs):
            return fake_response

    class FakeClientContext:
        def __enter__(self):
            return SimpleNamespace(models=FakeModels())

        def __exit__(self, *_args):
            return None

    fake_adapter = SimpleNamespace(_client=lambda: FakeClientContext())

    async def run():
        monkeypatch.setattr(work_agent, "get_gemini_model", lambda *_args, **_kwargs: fake_adapter)
        text, calls, usage, assistant_state = await work_agent._gemini_turn(
            model=resolve_model("velora"),
            system="Work agent",
            contents=["Research Pinaceae."],
            effort="extra",
            timeout_seconds=10,
            tool_definitions=[],
        )
        assert text == ""
        assert calls == [{
            "id": "native-google-call-42",
            "native_id": "native-google-call-42",
            "name": "web_search",
            "arguments": {"query": "Pinaceae"},
        }]
        assert assistant_state is function_content

    asyncio.run(run())

def test_readable_html_exposes_page_title_and_safe_navigation_links():
    parser = work_agent._ReadableHTML()
    parser.feed(
        "<html><head><title>Official Documentation</title></head><body>"
        '<a href="/guide"> User Guide </a>'
        '<a href="https://docs.example.org/api#top">API Reference</a>'
        '<a href="javascript:alert(1)">Unsafe Link</a>'
        '<a href="mailto:help@example.org">Email</a>'
        '<a href="//example.com/current">Same Page</a>'
        "</body></html>"
    )
    parser.close()

    assert " ".join(parser.title_parts) == "Official Documentation"
    links = work_agent._public_navigation_links(
        parser.links,
        "https://example.com/current",
    )
    assert links == [
        {"label": "User Guide", "url": "https://example.com/guide"},
        {"label": "API Reference", "url": "https://docs.example.org/api"},
    ]
