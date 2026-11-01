"""Session Live bidirectionnelle audio/vidéo avec Gemini."""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
from decimal import Decimal, ROUND_CEILING
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from llink_api.config import get_settings
from llink_api.database import get_db
from llink_api.providers.openai_compatible import TokenUsage
from llink_api.security import _decode_firebase_token
from llink_api.services.ai_slots import reserve_ai_slot
from llink_api.services.entitlements import resolve_entitled_level
from llink_api.services.model_registry import ModelDefinition
from llink_api.services.security_limits import enforce_endpoint_quota
from llink_api.services.usage_meter import finalize_usage, reserve_usage_budget

logger = logging.getLogger(__name__)
router = APIRouter()

LIVE_MODEL = "gemini-3.8-live"
LIVE_MAX_SECONDS = 600
MAX_AUDIO_CHUNK_BYTES = 48_000
MAX_VIDEO_FRAME_BYTES = 750_000
MAX_TEXT_CHARS = 8_000
MAX_SESSION_TEXT_CHARS = 40_000

# Gemini Live Standard rates on 2026-11-01, in USD per million modality tokens.
LIVE_INPUT_RATES = {
    "AUDIO": Decimal("3.00"),
    "TEXT": Decimal("0.75"),
    "IMAGE": Decimal("1.00"),
    "VIDEO": Decimal("1.00"),
}
# Gemini 3.8 Live Standard output audio rate (Google pricing, 2026-11-01).
# The official Standard tier remains $12 / million audio tokens; do not confuse it
# with the higher Priority tier's $21.60 rate.
LIVE_OUTPUT_AUDIO_USD_PER_MILLION = Decimal(
    os.getenv("LLINK_LIVE_AUDIO_OUTPUT_USD_PER_MILLION", "12.00")
)
LIVE_OUTPUT_RATES = {
    "AUDIO": LIVE_OUTPUT_AUDIO_USD_PER_MILLION,
    "TEXT": Decimal("4.50"),
}
LIVE_USAGE_MODEL = ModelDefinition(
    level="velora",
    label="GEMINI LIVE",
    provider="gemini",
    model_id=LIVE_MODEL,
    display_model="Gemini 3.8 Live",
    input_usd_per_million=Decimal("3.00"),
    output_usd_per_million=LIVE_OUTPUT_AUDIO_USD_PER_MILLION,
    cached_input_usd_per_million=Decimal("0.30"),
    max_output_tokens=15_000,
)


def build_live_config() -> dict[str, Any]:
    """Configuration audio native, transcription dans les deux directions et voix Elia."""
    return {
        "response_modalities": ["AUDIO"],
        "media_resolution": types.MediaResolution.MEDIA_RESOLUTION_LOW,
        "speech_config": {
            "voice_config": {
                "prebuilt_voice_config": {"voice_name": "Kore"}
            }
        },
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "system_instruction": (
            "Tu es Elia, la voix conversationnelle de Llink, l'assistant IA de CRYPT. "
            "Tu parles naturellement en français par défaut, mais tu peux converser dans "
            "la langue de ton interlocuteur. Réponds oralement avec des phrases fluides, "
            "claires et plutôt concises. Tu peux écouter, interrompre et reprendre la "
            "conversation. Quand l'utilisateur montre quelque chose avec la caméra, "
            "décris uniquement ce que tu peux réellement observer. N'invente rien. "
            "Ne prétends jamais avoir accès à une caméra, un microphone, un fichier ou "
            "une donnée qui ne t'a pas été transmis pendant la session."
        ),
    }


async def _safe_send(websocket: WebSocket, payload: dict[str, Any]) -> bool:
    try:
        await websocket.send_json(payload)
        return True
    except Exception:
        return False


def _decode_chunk(payload: Any, *, maximum: int, label: str) -> bytes:
    if not isinstance(payload, str) or not payload:
        raise ValueError(f"Contenu {label} invalide.")
    if len(payload) > ((maximum + 2) // 3) * 4 + 8:
        raise ValueError(f"Le bloc {label} dépasse la limite autorisée.")
    try:
        result = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Encodage Base64 {label} invalide.") from exc
    if not result or len(result) > maximum:
        raise ValueError(f"Le bloc {label} dépasse la limite autorisée.")
    return result


def _detail_counts(details: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in details or []:
        modality = getattr(item, "modality", "")
        modality = getattr(modality, "name", modality)
        modality = str(modality).upper().split(".")[-1]
        try:
            count = max(0, int(getattr(item, "token_count", 0) or 0))
        except (TypeError, ValueError):
            continue
        if modality and count:
            counts[modality] = counts.get(modality, 0) + count
    return counts


def live_token_usage(metadata: Any) -> TokenUsage | None:
    """Convertit les compteurs par modalité Gemini Live en coût USD contrôlé."""
    if metadata is None:
        return None
    prompt_tokens = getattr(metadata, "prompt_token_count", None)
    completion_tokens = getattr(metadata, "response_token_count", None)
    if completion_tokens is None:
        completion_tokens = getattr(metadata, "candidates_token_count", None)
    if prompt_tokens is None or completion_tokens is None:
        return None
    try:
        prompt_tokens = max(0, int(prompt_tokens))
        completion_tokens = max(0, int(completion_tokens))
        cached_tokens = max(0, int(getattr(metadata, "cached_content_token_count", 0) or 0))
    except (TypeError, ValueError):
        return None

    input_details = _detail_counts(getattr(metadata, "prompt_tokens_details", None))
    output_details = _detail_counts(
        getattr(metadata, "response_tokens_details", None)
        or getattr(metadata, "candidates_tokens_details", None)
    )
    if input_details:
        input_cost = sum(
            Decimal(count) * LIVE_INPUT_RATES.get(modality, LIVE_INPUT_RATES["AUDIO"])
            for modality, count in input_details.items()
        )
    else:
        input_cost = Decimal(prompt_tokens) * LIVE_INPUT_RATES["AUDIO"]

    if output_details:
        output_cost = sum(
            Decimal(count) * LIVE_OUTPUT_RATES.get(modality, LIVE_OUTPUT_RATES["AUDIO"])
            for modality, count in output_details.items()
        )
    else:
        output_cost = Decimal(completion_tokens) * LIVE_OUTPUT_RATES["AUDIO"]

    cost_microusd = int(
        ((input_cost + output_cost) / Decimal(1_000_000) * Decimal(1_000_000))
        .to_integral_value(rounding=ROUND_CEILING)
    )
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_input_tokens=min(prompt_tokens, cached_tokens),
        cost_microusd=cost_microusd,
    )


async def _receive_client_events(websocket: WebSocket, session: Any) -> None:
    session_text_chars = 0
    while True:
        event = await websocket.receive_json()
        if not isinstance(event, dict):
            raise ValueError("Événement Live invalide.")

        event_type = event.get("type")
        if event_type == "audio":
            audio = _decode_chunk(
                event.get("data"),
                maximum=MAX_AUDIO_CHUNK_BYTES,
                label="audio",
            )
            await session.send_realtime_input(
                audio=types.Blob(
                    data=audio,
                    mime_type="audio/pcm;rate=16000",
                )
            )
        elif event_type == "audio_end":
            await session.send_realtime_input(audio_stream_end=True)
        elif event_type == "ping":
            await _safe_send(websocket, {"type": "pong"})
        elif event_type == "video":
            frame = _decode_chunk(
                event.get("data"),
                maximum=MAX_VIDEO_FRAME_BYTES,
                label="image",
            )
            await session.send_realtime_input(
                video=types.Blob(data=frame, mime_type="image/jpeg")
            )
        elif event_type == "text":
            text = event.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
                raise ValueError("Message texte Live vide ou trop long.")
            session_text_chars += len(text)
            if session_text_chars > MAX_SESSION_TEXT_CHARS:
                raise ValueError("La limite de texte de cette session Live est atteinte.")
            await session.send_realtime_input(text=text.strip())
        elif event_type == "close":
            return
        else:
            raise ValueError("Type d'événement Live non pris en charge.")


async def _forward_model_events(
    websocket: WebSocket,
    session: Any,
    usage_state: dict[str, Any],
) -> None:
    async for response in session.receive():
        current_usage = live_token_usage(getattr(response, "usage_metadata", None))
        if current_usage is not None:
            usage_state["usage"] = current_usage
        content = getattr(response, "server_content", None)
        if content is None:
            continue

        if getattr(content, "interrupted", False):
            if not await _safe_send(websocket, {"type": "interrupted"}):
                return

        input_transcription = getattr(content, "input_transcription", None)
        if input_transcription is not None:
            text = getattr(input_transcription, "text", None)
            if text:
                if not await _safe_send(
                    websocket, {"type": "transcript", "speaker": "user", "text": text}
                ):
                    return

        output_transcription = getattr(content, "output_transcription", None)
        if output_transcription is not None:
            text = getattr(output_transcription, "text", None)
            if text:
                if not await _safe_send(
                    websocket, {"type": "transcript", "speaker": "assistant", "text": text}
                ):
                    return

        model_turn = getattr(content, "model_turn", None)
        for part in getattr(model_turn, "parts", []) or []:
            inline_data = getattr(part, "inline_data", None)
            audio_data = getattr(inline_data, "data", None) if inline_data else None
            if not audio_data:
                continue
            if isinstance(audio_data, str):
                encoded = audio_data
            else:
                encoded = base64.b64encode(bytes(audio_data)).decode("ascii")
            if not await _safe_send(
                websocket,
                {
                    "type": "audio",
                    "mime_type": getattr(inline_data, "mime_type", None) or "audio/pcm;rate=24000",
                    "sample_rate": 24000,
                    "data": encoded,
                },
            ):
                return

        if getattr(content, "turn_complete", False):
            if not await _safe_send(websocket, {"type": "turn_complete"}):
                return


@router.websocket("/ws/live")
async def live_websocket(websocket: WebSocket) -> None:
    """Relais WebSocket authentifié : navigateur ↔ FastAPI ↔ Gemini Live API."""
    settings = get_settings()
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.cors_origins:
        await websocket.close(code=4403, reason="Origine non autorisée.")
        return

    await websocket.accept()
    release_slot = None
    reservation = None
    usage_state: dict[str, Any] = {"usage": None}
    user_uid = "anonymous"
    entitled_level = "velora"
    session_started = False
    final_status = "not_started"
    db = get_db()
    try:
        try:
            first = await asyncio.wait_for(websocket.receive_json(), timeout=15)
        except (asyncio.TimeoutError, ValueError):
            await _safe_send(websocket, {"type": "error", "message": "Authentification Live expirée."})
            await websocket.close(code=4401)
            return

        if not isinstance(first, dict) or first.get("type") != "auth":
            await _safe_send(websocket, {"type": "error", "message": "Authentification requise pour Live."})
            await websocket.close(code=4401)
            return

        token = first.get("token")
        if not isinstance(token, str) or not token.strip():
            await _safe_send(websocket, {"type": "error", "message": "Connecte-toi pour utiliser Live."})
            await websocket.close(code=4401)
            return

        try:
            user = await asyncio.to_thread(_decode_firebase_token, token.strip())
        except Exception:
            await _safe_send(websocket, {"type": "error", "message": "Session expirée. Reconnecte-toi."})
            await websocket.close(code=4401)
            return

        user_uid = str(user.get("uid") or "anonymous")
        if user_uid == "anonymous":
            await _safe_send(websocket, {"type": "error", "message": "Un compte connecté est requis pour Live."})
            await websocket.close(code=4401)
            return

        if not settings.gemini_api_key:
            await _safe_send(websocket, {"type": "error", "message": "Le service vocal n'est pas configuré sur le serveur."})
            await websocket.close(code=4503)
            return

        await enforce_endpoint_quota(
            request=websocket,
            user=user,
            db=db,
            scope="live",
        )
        entitled_level = await asyncio.to_thread(resolve_entitled_level, user, db)
        release_slot = await reserve_ai_slot()
        try:
            # Conservative 10-minute ceiling; actual provider modality usage settles it.
            reservation = await reserve_usage_budget(
                db=db,
                uid=user_uid,
                level=entitled_level,
                model=LIVE_USAGE_MODEL,
                prompt=" " * 380_000,
            )
        except Exception:
            release_slot()
            release_slot = None
            raise

        client = genai.Client(api_key=settings.gemini_api_key)
        config = build_live_config()
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            session_started = True
            final_status = "completed"
            await websocket.send_json(
                {"type": "ready", "model": LIVE_MODEL, "max_duration_seconds": LIVE_MAX_SECONDS}
            )
            sender = asyncio.create_task(_receive_client_events(websocket, session))
            receiver = asyncio.create_task(_forward_model_events(websocket, session, usage_state))
            duration_guard = asyncio.create_task(asyncio.sleep(LIVE_MAX_SECONDS))
            tasks = {sender, receiver, duration_guard}

            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if duration_guard in done:
                final_status = "duration_limit"
                await _safe_send(
                    websocket,
                    {
                        "type": "error",
                        "message": "Cette session Live a atteint sa durée maximale de 10 minutes.",
                    },
                )
                try:
                    await websocket.close(code=1000, reason="Durée maximale atteinte.")
                except Exception:
                    pass
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                if task is not duration_guard:
                    exception = task.exception()
                    if exception is not None:
                        raise exception

    except WebSocketDisconnect:
        final_status = "disconnected"
    except ValueError as exc:
        final_status = "invalid_input"
        await _safe_send(websocket, {"type": "error", "message": str(exc)})
        try:
            await websocket.close(code=4400)
        except Exception:
            pass
    except Exception:
        final_status = "provider_error"
        logger.exception("La session Gemini Live a échoué.")
        await _safe_send(
            websocket,
            {"type": "error", "message": "La session vocale a été interrompue. Réessaie."},
        )
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        if reservation is not None:
            # If the provider never opened a session, release the reservation at zero cost.
            final_usage = usage_state["usage"]
            if not session_started:
                final_usage = TokenUsage(0, 0, cost_microusd=0)
            try:
                await finalize_usage(
                    db=db,
                    uid=user_uid,
                    reservation=reservation,
                    level=entitled_level,
                    model=LIVE_USAGE_MODEL,
                    usage=final_usage,
                    status=final_status,
                )
            except Exception:
                logger.exception("Impossible de finaliser la consommation Gemini Live.")
        if release_slot is not None:
            release_slot()
