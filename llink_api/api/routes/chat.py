"""Route de chat avec registre de modèles, contrôle des droits et suivi des coûts."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from llink_api.config import get_settings
from llink_api.database import get_db
from llink_api.providers.gemini import get_gemini_model
from llink_api.providers.openai_compatible import (
    ProviderEvent,
    TokenUsage,
    stream_openai_compatible,
)
from llink_api.schemas import ChatPayload
from llink_api.security import get_optional_user
from llink_api.services.ai_slots import reserve_ai_slot
from llink_api.services.entitlements import resolve_entitled_level
from llink_api.services.model_registry import ModelDefinition, resolve_model, user_can_access_level
from llink_api.services.security_limits import enforce_endpoint_quota
from llink_api.services.training_data import record_exchange_if_consented
from llink_api.services.usage_meter import (
    UsageReservation,
    finalize_usage,
    reserve_usage_budget,
)

logger = logging.getLogger(__name__)
router = APIRouter()

STREAM_HEADERS = {
    "X-Accel-Buffering": "no",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
}


def build_system_instruction(mode: str | None, preferences: str | None) -> str:
    if mode == "translate":
        instruction = (
            "Tu es un traducteur expert. Tu ne dois donner QUE la traduction exacte, "
            "sans aucune explication, ni commentaire, ni introduction. Traduis mot pour mot."
        )
    else:
        instruction = (
            "Tu es Llink (Luga Link), une IA d'assistance et de traduction créée par CRYPT. "
            "Tu es précis et structuré. Ne répond jamais à une question qu'on ne t'a pas "
            "demandé. Réponds toujours dans la langue de l'utilisateur. Si on ne te demande "
            "pas une longue réponse, donne toujours la réponse la plus courte possible mais "
            "la plus efficace. Le PDG de CRYPT (Core Resolution Yield Plateform Technologie) "
            "est KL Gaby (Kahorha Gabriel) et cela fait de lui ton inventeur."
        )
    if preferences and mode != "translate":
        instruction += f" Prends en compte ces préférences strictes de l'utilisateur : {preferences}"
    return instruction


async def _iterate_sync(iterable):
    """Consomme un iterable SDK synchrone sans bloquer la boucle asyncio."""
    iterator = iter(iterable)
    sentinel = object()
    while True:
        item = await asyncio.to_thread(next, iterator, sentinel)
        if item is sentinel:
            break
        yield item


def _gemini_usage(chunk: Any) -> TokenUsage | None:
    metadata = getattr(chunk, "usage_metadata", None)
    if metadata is None:
        return None
    prompt = getattr(metadata, "prompt_token_count", None)
    completion = getattr(metadata, "candidates_token_count", None)
    if prompt is None or completion is None:
        return None
    cached = getattr(metadata, "cached_content_token_count", 0) or 0
    try:
        return TokenUsage(
            prompt_tokens=max(0, int(prompt)),
            completion_tokens=max(0, int(completion)),
            cached_input_tokens=max(0, int(cached)),
        )
    except (TypeError, ValueError):
        return None


def _provider_credentials(model: ModelDefinition) -> tuple[str, str]:
    settings = get_settings()
    if model.provider == "gemini":
        return settings.gemini_api_key, ""
    if model.provider == "zai":
        return settings.zai_api_key, settings.zai_base_url
    if model.provider == "minimax":
        return settings.minimax_api_key, settings.minimax_base_url
    if model.provider == "deepseek":
        return settings.deepseek_api_key, settings.deepseek_base_url
    raise HTTPException(status_code=503, detail="Fournisseur IA non configuré.")


async def _record_if_requested(
    *,
    db: Any | None,
    payload: ChatPayload,
    user_uid: str,
    source: str,
    full_reply: str,
) -> None:
    await record_exchange_if_consented(
        db=db,
        prompt=payload.message,
        response=full_reply,
        user_uid=user_uid,
        source=source,
        preferences=payload.preferences,
        mode=payload.mode,
        consent=payload.data_collection_consent,
    )


@router.post("/api/chat")
async def chat_endpoint(
    payload: ChatPayload,
    request: Request,
    user: dict = Depends(get_optional_user),
    db: Any | None = Depends(get_db),
):
    await enforce_endpoint_quota(request=request, user=user, db=db, scope="chat")

    try:
        model = resolve_model(payload.level, payload.model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    uid = user.get("uid", "anonymous")
    entitled_level = await asyncio.to_thread(resolve_entitled_level, user, db)
    if not user_can_access_level(entitled_level, model.level):
        raise HTTPException(
            status_code=403,
            detail="Votre abonnement ne donne pas accès à ce niveau Llink.",
        )

    api_key, base_url = _provider_credentials(model)
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=f"Le fournisseur {model.provider} n'est pas configuré sur le serveur.",
        )

    system_instruction = build_system_instruction(payload.mode, payload.preferences)
    timeout = get_settings().provider_timeout_seconds

    release_slot = await reserve_ai_slot()
    try:
        reservation = await reserve_usage_budget(
            db=db,
            uid=uid,
            level=model.level,
            model=model,
            prompt=system_instruction + "\n" + payload.message,
        )
    except Exception:
        release_slot()
        raise

    request_source = payload.source or "llink_web"
    source_tag = f"anonymous_{request_source}" if uid == "anonymous" else request_source

    async def settle_and_release(
        usage: TokenUsage | None,
        status: str,
    ) -> None:
        try:
            await finalize_usage(
                db=db,
                uid=uid,
                reservation=reservation,
                level=model.level,
                model=model,
                usage=usage,
                status=status,
            )
        except Exception:
            logger.exception("Erreur inattendue de comptabilisation.")
        finally:
            release_slot()

    async def cleanup_if_stream_not_consumed() -> None:
        # La finalisation est idempotente : elle ne remplace pas une mesure déjà écrite.
        await settle_and_release(None, "stream_not_consumed")

    async def provider_generator():
        full_reply = ""
        usage: TokenUsage | None = None
        status = "completed"
        try:
            if model.provider == "gemini":
                gemini_model = get_gemini_model(
                    system_instruction,
                    model_name=model.model_id,
                )
                response = await asyncio.to_thread(
                    gemini_model.generate_content,
                    payload.message,
                    stream=True,
                    request_options={"timeout": timeout},
                )
                async for chunk in _iterate_sync(response):
                    current_usage = _gemini_usage(chunk)
                    if current_usage is not None:
                        usage = current_usage
                    try:
                        fragment = getattr(chunk, "text", None)
                    except Exception:
                        fragment = None
                    if fragment:
                        full_reply += fragment
                        yield fragment
            else:
                async for event in stream_openai_compatible(
                    provider=model.provider,
                    base_url=base_url,
                    api_key=api_key,
                    model_id=model.model_id,
                    system_instruction=system_instruction,
                    user_text=payload.message,
                    effort=payload.effort,
                    max_output_tokens=model.max_output_tokens,
                    timeout_seconds=timeout,
                ):
                    if event.usage is not None:
                        usage = event.usage
                    if event.text:
                        full_reply += event.text
                        yield event.text

            if full_reply:
                await _record_if_requested(
                    db=db,
                    payload=payload,
                    user_uid=uid,
                    source=source_tag,
                    full_reply=full_reply,
                )
            if usage is None:
                status = "completed_usage_missing"
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception:
            status = "provider_error"
            logger.exception(
                "Échec du flux IA (provider=%s, level=%s, model=%s).",
                model.provider,
                model.level,
                model.model_id,
            )
            yield "❌ Le service IA est temporairement indisponible. Réessayez."
        finally:
            await settle_and_release(usage, status)

    return StreamingResponse(
        provider_generator(),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
        background=BackgroundTask(cleanup_if_stream_not_consumed),
    )
