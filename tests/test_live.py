"""Tests du WebSocket Live et de la consommation multimodale."""

from types import SimpleNamespace

import pytest

from llink_api.api.routes.live import (
    LIVE_MODEL,
    _decode_chunk,
    build_live_config,
    default_live_audio_output_rate,
    live_token_usage,
)
from llink_api.services.security_limits import get_quota_policy


def test_live_config_uses_audio_modalities_and_transcriptions():
    config = build_live_config()
    assert config["response_modalities"] == ["AUDIO"]
    assert config["input_audio_transcription"] == {}
    assert config["output_audio_transcription"] == {}
    assert config["speech_config"]["voice_config"]["prebuilt_voice_config"]["voice_name"] == "Kore"
    assert LIVE_MODEL == "gemini-3.1-flash-live-preview"


def test_live_audio_and_image_chunks_validate_base64():
    import base64

    payload = b"\x00\x01\x02\x03"
    encoded = base64.b64encode(payload).decode("ascii")
    assert _decode_chunk(encoded, maximum=100, label="audio") == payload


def test_live_chunk_rejects_malformed_base64_and_oversized_data():
    with pytest.raises(ValueError):
        _decode_chunk("not-base64!", maximum=100, label="audio")
    with pytest.raises(ValueError):
        _decode_chunk("QUJDREVGRw==", maximum=3, label="audio")


def test_live_usage_calculates_cost_from_modality_breakdown():
    metadata = SimpleNamespace(
        prompt_token_count=100,
        response_token_count=50,
        cached_content_token_count=0,
        prompt_tokens_details=[
            SimpleNamespace(modality="AUDIO", token_count=80),
            SimpleNamespace(modality="TEXT", token_count=20),
        ],
        response_tokens_details=[
            SimpleNamespace(modality="AUDIO", token_count=40),
            SimpleNamespace(modality="TEXT", token_count=10),
        ],
    )
    usage = live_token_usage(metadata)
    assert usage is not None
    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 50
    # 80*3 + 20*0.75 + 40*12 + 10*4.5 = 780 micro-USD.
    assert usage.cost_microusd == 780


def test_live_usage_returns_none_without_provider_usage():
    assert live_token_usage(None) is None


def test_live_quota_is_account_only():
    policy = get_quota_policy("live", authenticated=True)
    assert (policy.per_minute, policy.per_day) == (1, 12)
    with pytest.raises(RuntimeError):
        get_quota_policy("live", authenticated=False)


def test_live_websocket_rejects_empty_firebase_token(client):
    with client.websocket_connect("/ws/live") as websocket:
        websocket.send_json({"type": "auth", "token": ""})
        response = websocket.receive_json()
    assert response["type"] == "error"
    assert "Connecte-toi" in response["message"]


def test_live_output_rate_changes_on_scheduled_google_price_date():
    from datetime import date
    from decimal import Decimal

    assert default_live_audio_output_rate(date(2026, 12, 31)) == Decimal("12.00")
    assert default_live_audio_output_rate(date(2027, 1, 1)) == Decimal("21.60")
