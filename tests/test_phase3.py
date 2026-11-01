"""Tests du registre de modèles, droits, streaming et métriques Phase 3."""

import asyncio

from llink_api.config import get_settings
from llink_api.api.routes.chat import build_system_instruction
from llink_api.providers.openai_compatible import TokenUsage, parse_stream_payload
from llink_api.services.entitlements import resolve_entitled_level
from llink_api.services.model_registry import (
    MODEL_REGISTRY,
    resolve_model,
    user_can_access_level,
)
from llink_api.services.security_limits import get_quota_policy
from llink_api.services.usage_meter import calculate_cost_microusd


def test_explicit_level_overrides_legacy_model_alias():
    model = resolve_model("omnis", "gemini-1.5-flash")
    assert model.level == "omnis"
    assert model.provider == "zai"
    assert model.model_id == "glm-5"


def test_legacy_aliases_are_preserved():
    assert resolve_model(None, "gemini-1.5-flash").level == "velora"
    assert resolve_model(None, "deepseek-v3").level == "satori"
    assert resolve_model(None, "mistral-7b").level == "satori"


def test_registry_contains_all_five_levels():
    assert tuple(MODEL_REGISTRY) == ("velora", "satori", "noetra", "auren", "omnis")


def test_entitlement_order_enforces_upgrade_boundaries():
    assert user_can_access_level("omnis", "auren")
    assert user_can_access_level("satori", "velora")
    assert not user_can_access_level("satori", "noetra")
    assert not user_can_access_level("velora", "satori")


def test_anonymous_entitlement_is_always_velora():
    assert resolve_entitled_level({"uid": "anonymous"}, None) == "velora"


def test_legacy_pro_document_without_plan_fails_closed():
    class Snapshot:
        exists = True

        def to_dict(self):
            return {"isPro": True, "expirationDate": 4_000_000_000}

    class Document:
        def get(self):
            return Snapshot()

    class Collection:
        def document(self, _uid):
            return Document()

    class Database:
        def collection(self, _name):
            return Collection()

    assert resolve_entitled_level({"uid": "user-1"}, Database()) == "velora"


def test_verified_subscription_plan_maps_to_entitled_level():
    class Snapshot:
        exists = True

        def to_dict(self):
            return {
                "isPro": True,
                "subscriptionPlan": "gold",
                "expirationDate": 4_000_000_000,
            }

    class Document:
        def get(self):
            return Snapshot()

    class Collection:
        def document(self, _uid):
            return Document()

    class Database:
        def collection(self, _name):
            return Collection()

    assert resolve_entitled_level({"uid": "user-1"}, Database()) == "auren"


def test_expired_subscription_falls_back_to_velora():
    class Snapshot:
        exists = True

        def to_dict(self):
            return {
                "isPro": True,
                "subscriptionPlan": "diamant",
                "expirationDate": 1,
            }

    class Document:
        def get(self):
            return Snapshot()

    class Collection:
        def document(self, _uid):
            return Document()

    class Database:
        def collection(self, _name):
            return Collection()

    assert resolve_entitled_level({"uid": "user-1"}, Database()) == "velora"


def test_openai_compatible_parser_excludes_private_reasoning_content():
    event = parse_stream_payload({
        "choices": [{
            "delta": {
                "content": "Réponse publique",
                "reasoning_content": "raisonnement interne",
            }
        }],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 10},
        },
    })
    assert event.text == "Réponse publique"
    assert event.usage == TokenUsage(
        prompt_tokens=100,
        completion_tokens=20,
        cached_input_tokens=10,
    )


def test_usage_only_stream_chunk_is_parsed():
    event = parse_stream_payload({
        "choices": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    })
    assert event.text is None
    assert event.usage == TokenUsage(prompt_tokens=10, completion_tokens=5)


def test_cost_estimate_uses_cached_input_and_output_rates():
    model = MODEL_REGISTRY["velora"]
    cost = calculate_cost_microusd(
        model,
        TokenUsage(
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            cached_input_tokens=200_000,
        ),
    )
    # 0.8M * $0.30 + 0.2M * $0.03 + 1M * $2.50 = $2.746.
    assert cost == 2_746_000


def test_hourly_budgets_are_optional_and_read_from_server_config(monkeypatch):
    monkeypatch.delenv("LLINK_HOURLY_CREDIT_LIMITS_USD", raising=False)
    assert get_settings().hourly_credit_limits_usd == {}
    monkeypatch.setenv(
        "LLINK_HOURLY_CREDIT_LIMITS_USD",
        '{"velora": 0.50, "satori": 2.0}',
    )
    assert get_settings().hourly_credit_limits_usd == {"velora": 0.5, "satori": 2.0}


def test_invalid_hourly_budget_configuration_is_rejected(monkeypatch):
    import pytest

    monkeypatch.setenv("LLINK_HOURLY_CREDIT_LIMITS_USD", '{"velora": -1}')
    with pytest.raises(ValueError):
        get_settings()


def test_usage_read_quota_is_defined():
    assert get_quota_policy("usage_read", authenticated=True).per_minute == 30
    assert get_quota_policy("usage_read", authenticated=True).per_day == 200


def test_gemini_sync_adapter_still_accepts_iterable_response_objects():
    from llink_api.api.routes.chat import _iterate_sync

    class GeminiLikeResponse:
        def __iter__(self):
            return iter(["one", "two"])

    async def collect():
        return [item async for item in _iterate_sync(GeminiLikeResponse())]

    assert asyncio.run(collect()) == ["one", "two"]


async def _async_return(value):
    return value


def test_chat_route_rejects_a_tier_not_present_in_server_entitlements(client, monkeypatch):
    from llink_api.api.routes import chat as chat_route

    async def no_quota(**_kwargs):
        return None

    monkeypatch.setattr(chat_route, "enforce_endpoint_quota", no_quota)
    monkeypatch.setattr(chat_route, "resolve_entitled_level", lambda _user, _db: "velora")
    response = client.post(
        "/api/chat",
        json={
            "message": "Test",
            "model": "gemini-1.5-flash",
            "level": "omnis",
        },
    )
    assert response.status_code == 403
    assert "abonnement" in response.json()["detail"].lower()


def test_gemini_chat_preserves_plain_text_streaming_contract(client, monkeypatch):
    from types import SimpleNamespace

    from llink_api.api.routes import chat as chat_route

    async def no_quota(**_kwargs):
        return None

    async def no_budget(**_kwargs):
        return None

    async def no_training(**_kwargs):
        return None

    class FakeResponse:
        def __iter__(self):
            return iter([
                SimpleNamespace(text="Bonjour ", usage_metadata=None),
                SimpleNamespace(
                    text="depuis Gemini",
                    usage_metadata=SimpleNamespace(
                        prompt_token_count=12,
                        candidates_token_count=4,
                        cached_content_token_count=0,
                    ),
                ),
            ])

    class FakeModel:
        def generate_content(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(chat_route, "enforce_endpoint_quota", no_quota)
    monkeypatch.setattr(chat_route, "resolve_entitled_level", lambda _user, _db: "velora")
    monkeypatch.setattr(chat_route, "_provider_credentials", lambda _model: ("fake-key", ""))
    monkeypatch.setattr(chat_route, "reserve_ai_slot", lambda: _async_return(lambda: None))
    monkeypatch.setattr(chat_route, "reserve_usage_budget", no_budget)
    monkeypatch.setattr(chat_route, "get_gemini_model", lambda *_args, **_kwargs: FakeModel())
    monkeypatch.setattr(chat_route, "_record_if_requested", no_training)

    response = client.post(
        "/api/chat",
        json={
            "message": "Bonjour",
            "model": "gemini-1.5-flash",
            "level": "velora",
            "effort": "normal",
        },
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert response.text == "Bonjour depuis Gemini"



def test_provider_stream_sends_server_model_effort_and_usage_options(monkeypatch):
    from llink_api.providers import openai_compatible

    captured = {}

    class FakeResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def aiter_lines(self):
            yield (
                'data: {"choices":[{"delta":{"content":"Réponse","reasoning_content":"secret"}}]}'
            )
            yield (
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
                '"usage":{"prompt_tokens":15,"completion_tokens":9}}'
            )
            yield "data: [DONE]"

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, method, url, *, json, headers):
            captured.update({
                "method": method,
                "url": url,
                "payload": json,
                "headers": headers,
            })
            return FakeResponse()

    monkeypatch.setattr(openai_compatible.httpx, "AsyncClient", FakeClient)

    async def collect():
        return [
            event
            async for event in openai_compatible.stream_openai_compatible(
                provider="deepseek",
                base_url="https://api.deepseek.com",
                api_key="test-secret",
                model_id="deepseek-flash",
                system_instruction="Tu es Llink.",
                user_text="Bonjour",
                effort="ultime",
                max_output_tokens=2048,
                timeout_seconds=30,
            )
        ]

    events = asyncio.run(collect())
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["payload"]["model"] == "deepseek-flash"
    assert captured["payload"]["reasoning_effort"] == "max"
    assert captured["payload"]["thinking"] == {"type": "enabled"}
    assert captured["payload"]["stream_options"] == {"include_usage": True}
    assert [event.text for event in events if event.text] == ["Réponse"]
    assert events[-1].usage == TokenUsage(prompt_tokens=15, completion_tokens=9)



def test_gemini_adapter_maps_effort_to_official_thinking_config(monkeypatch):
    from llink_api.providers import gemini as gemini_provider

    captured = {}

    class FakeModels:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {"text": "ok"})()

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.models = FakeModels()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(gemini_provider.genai, "Client", FakeClient)
    monkeypatch.setattr(
        gemini_provider,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"gemini_api_key": "fake-key", "provider_timeout_seconds": 21},
        )(),
    )

    model = gemini_provider.get_gemini_model(
        "System instruction",
        model_name="gemini-3.5-flash-lite",
        effort="ultime",
    )
    response = model.generate_content("Bonjour")

    assert response.text == "ok"
    assert captured["model"] == "gemini-3.5-flash-lite"
    assert captured["config"].thinking_config.thinking_level.value == "HIGH"
    assert captured["config"].system_instruction == "System instruction"
    assert captured["config"].max_output_tokens == 2048
    assert captured["client_kwargs"]["http_options"].timeout == 21_000



def test_gemini_adapter_converts_legacy_multimedia_parts():
    from llink_api.providers.gemini import GeminiModelAdapter

    normalized = GeminiModelAdapter._normalize_contents([
        "Transcris ceci",
        {"mime_type": "audio/webm", "data": b"audio-bytes"},
    ])

    assert normalized[0] == "Transcris ceci"
    assert normalized[1].inline_data.mime_type == "audio/webm"
    assert normalized[1].inline_data.data == b"audio-bytes"



def test_openai_chat_messages_include_previous_turns_in_order():
    from llink_api.providers.openai_compatible import build_chat_messages

    messages = build_chat_messages(
        "Instruction système",
        [
            {"role": "user", "content": "Bonjour"},
            {"role": "assistant", "content": "Salut !"},
        ],
        "Et ensuite ?",
    )
    assert messages == [
        {"role": "system", "content": "Instruction système"},
        {"role": "user", "content": "Bonjour"},
        {"role": "assistant", "content": "Salut !"},
        {"role": "user", "content": "Et ensuite ?"},
    ]


def test_gemini_chat_contents_map_assistant_to_model_role():
    from llink_api.providers.gemini import build_gemini_contents

    contents = build_gemini_contents(
        [
            {"role": "user", "content": "Bonjour"},
            {"role": "assistant", "content": "Salut !"},
        ],
        "Et ensuite ?",
    )
    assert [item.role for item in contents] == ["user", "model", "user"]
    assert [item.parts[0].text for item in contents] == ["Bonjour", "Salut !", "Et ensuite ?"]


def test_chat_history_is_normalized_and_bounded():
    from llink_api.api.routes.chat import (
        MAX_HISTORY_CHARS,
        normalize_conversation_history,
    )
    from llink_api.schemas import ConversationTurn

    history = [
        ConversationTurn(role="user", text="A" * MAX_HISTORY_CHARS),
        ConversationTurn(role="bot", text="Réponse récente"),
    ]
    normalized = normalize_conversation_history(history)
    assert normalized[-1] == {"role": "assistant", "content": "Réponse récente"}
    assert sum(len(item["content"]) for item in normalized) <= MAX_HISTORY_CHARS



def test_translate_instruction_respects_selected_languages():
    instruction = build_system_instruction("translate", None, "fr", "ln")
    assert "français" in instruction
    assert "lingala" in instruction
    assert "uniquement la traduction" in instruction.lower()


def test_translate_instruction_supports_auto_source_detection():
    instruction = build_system_instruction("translate", None, "auto", "en")
    assert "Détecte automatiquement" in instruction
    assert "anglais" in instruction
