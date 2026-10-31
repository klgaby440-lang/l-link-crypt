"""Route de chat et orchestration minimale des fournisseurs existants."""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from llink_api.config import get_settings
from llink_api.database import get_db
from llink_api.providers.gemini import get_gemini_model
from llink_api.providers.huggingface import (
    resolve_huggingface_model,
    stream_huggingface,
)
from llink_api.schemas import ChatPayload
from llink_api.security import verify_token
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
    user: dict = Depends(verify_token),
    db: Any | None = Depends(get_db),
):
    user_text = payload.message
    selected_model = payload.model
    mode = payload.mode
    uid = user.get("uid", "anonymous")
    request_source = payload.source or "llink_web"
    source_tag = f"anonymous_{request_source}" if uid == "anonymous" else request_source
    system_instruction = build_system_instruction(mode, payload.preferences)

    if "gemini" in selected_model.lower():

        async def gemini_generator():
            full_reply = ""
            try:
                model = get_gemini_model(system_instruction)
                response = model.generate_content(user_text, stream=True)
                for chunk in response:
                    if getattr(chunk, "text", None):
                        full_reply += chunk.text
                        yield chunk.text
                await _record_if_requested(
                    db=db,
                    payload=payload,
                    user_uid=uid,
                    source=source_tag,
                    full_reply=full_reply,
                )
            except Exception as exc:
                logger.exception("Erreur pendant le streaming Gemini.")
                yield f"❌ Erreur Gemini en cours de flux : {exc}"

        return StreamingResponse(
            gemini_generator(),
            media_type="text/event-stream",
            headers=STREAM_HEADERS,
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
                db=db,
                payload=payload,
                user_uid=uid,
                source=source_tag,
                full_reply=full_reply,
            )
            return
        except Exception as exc:
            logger.warning("Hugging Face indisponible ; bascule vers Gemini : %s", exc)

        full_reply = ""
        try:
            model = get_gemini_model(system_instruction)
            backup_response = model.generate_content(user_text, stream=True)
            for chunk in backup_response:
                if getattr(chunk, "text", None):
                    full_reply += chunk.text
                    yield chunk.text
            await _record_if_requested(
                db=db,
                payload=payload,
                user_uid=uid,
                source=source_tag,
                full_reply=full_reply,
            )
        except Exception as backup_error:
            logger.exception("Échec du fournisseur principal et du secours Gemini.")
            if not get_settings().gemini_api_key:
                yield "❌ Tous les serveurs sont indisponibles (Token HF et Clé Gemini manquants)."
            else:
                yield f"❌ Échec total de la génération. Détails : {backup_error}"

    return StreamingResponse(
        huggingface_generator(),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )
