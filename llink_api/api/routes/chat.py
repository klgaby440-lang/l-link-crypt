"""Route de chat avec quotas, file de concurrence et streaming borné."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from llink_api.config import get_settings
from llink_api.database import get_db
from llink_api.providers.gemini import get_gemini_model
from llink_api.providers.huggingface import resolve_huggingface_model, stream_huggingface
from llink_api.schemas import ChatPayload
from llink_api.security import get_optional_user
from llink_api.services.ai_slots import release_ai_slot, reserve_ai_slot
from llink_api.services.security_limits import enforce_endpoint_quota
from llink_api.services.training_data import record_exchange_if_consented

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


async def _iterate_sync(iterator):
    """Consomme un itérateur SDK synchrone sans bloquer la boucle asyncio."""
    sentinel = object()
    while True:
        item = await asyncio.to_thread(next, iterator, sentinel)
        if item is sentinel:
            break
        yield item


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
    await enforce_endpoint_quota(
        request=request, user=user, db=db, scope="chat"
    )
    await reserve_ai_slot()

    user_text = payload.message
    selected_model = payload.model
    uid = user.get("uid", "anonymous")
    request_source = payload.source or "llink_web"
    source_tag = f"anonymous_{request_source}" if uid == "anonymous" else request_source
    system_instruction = build_system_instruction(payload.mode, payload.preferences)
    timeout = get_settings().provider_timeout_seconds

    if "gemini" in selected_model.lower():

        async def gemini_generator():
            full_reply = ""
            try:
                model = get_gemini_model(system_instruction)
                response = await asyncio.to_thread(
                    model.generate_content,
                    user_text,
                    stream=True,
                    request_options={"timeout": timeout},
                )
                async for chunk in _iterate_sync(response):
                    fragment = getattr(chunk, "text", None)
                    if fragment:
                        full_reply += fragment
                        yield fragment
                await _record_if_requested(
                    db=db, payload=payload, user_uid=uid,
                    source=source_tag, full_reply=full_reply,
                )
            except Exception:
                logger.exception("Le fournisseur Gemini n'a pas terminé le flux.")
                yield "❌ Le service IA est temporairement indisponible. Réessayez."

        return StreamingResponse(
            gemini_generator(),
            media_type="text/event-stream",
            headers=STREAM_HEADERS,
            background=BackgroundTask(release_ai_slot),
        )

    hf_model = resolve_huggingface_model(selected_model)

    async def huggingface_generator():
        full_reply = ""
        try:
            async for fragment in stream_huggingface(
                model_id=hf_model,
                system_instruction=system_instruction,
                user_text=user_text,
            ):
                full_reply += fragment
                yield fragment

            await _record_if_requested(
                db=db, payload=payload, user_uid=uid,
                source=source_tag, full_reply=full_reply,
            )
            return
        except Exception:
            logger.warning("Le fournisseur Hugging Face est indisponible ; tentative de secours Gemini.")

        full_reply = ""
        try:
            model = get_gemini_model(system_instruction)
            backup_response = await asyncio.to_thread(
                model.generate_content,
                user_text,
                stream=True,
                request_options={"timeout": timeout},
            )
            async for chunk in _iterate_sync(backup_response):
                fragment = getattr(chunk, "text", None)
                if fragment:
                    full_reply += fragment
                    yield fragment
            await _record_if_requested(
                db=db, payload=payload, user_uid=uid,
                source=source_tag, full_reply=full_reply,
            )
        except Exception:
            logger.exception("Les fournisseurs IA principal et de secours ont échoué.")
            yield "❌ Les services IA sont temporairement indisponibles. Réessayez."

    return StreamingResponse(
        huggingface_generator(),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
        background=BackgroundTask(release_ai_slot),
    )
