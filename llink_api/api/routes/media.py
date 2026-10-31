"""Routes image/OCR et audio avec contrôles de taille, type, quotas et concurrence."""

import asyncio
import base64
import binascii
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from llink_api.config import get_settings
from llink_api.database import get_db
from llink_api.providers.gemini import get_gemini_model
from llink_api.schemas import AudioResponse, OCRRequest, OCRResponse
from llink_api.security import get_optional_user
from llink_api.services.ai_slots import reserve_ai_slot, release_ai_slot
from llink_api.services.security_limits import enforce_endpoint_quota

logger = logging.getLogger(__name__)
router = APIRouter()

SUPPORTED_AUDIO_MIME = {
    "audio/webm",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/ogg",
    "audio/aac",
}


def _decode_image_payload(value: str) -> tuple[bytes, str]:
    declared_mime = None
    encoded = value
    if value.startswith("data:"):
        header, separator, encoded = value.partition(",")
        if not separator or ";base64" not in header.lower():
            raise HTTPException(status_code=400, detail="Format image Base64 invalide.")
        declared_mime = header[5:].split(";", 1)[0].lower()

    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Image Base64 invalide.") from exc

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Image vide.")
    if len(image_bytes) > get_settings().max_image_bytes:
        raise HTTPException(status_code=413, detail="Image trop volumineuse.")

    if image_bytes.startswith(b"\xff\xd8\xff"):
        detected_mime = "image/jpeg"
    elif image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        detected_mime = "image/png"
    elif (
        len(image_bytes) >= 12
        and image_bytes.startswith(b"RIFF")
        and image_bytes[8:12] == b"WEBP"
    ):
        detected_mime = "image/webp"
    else:
        raise HTTPException(
            status_code=415,
            detail="Format image non pris en charge. Utilisez JPEG, PNG ou WebP.",
        )

    if declared_mime:
        normalized = "image/jpeg" if declared_mime == "image/jpg" else declared_mime
        if normalized != detected_mime:
            raise HTTPException(status_code=415, detail="Le type déclaré ne correspond pas au contenu de l'image.")
    return image_bytes, detected_mime


@router.post("/api/ocr", response_model=OCRResponse)
async def ocr_endpoint(
    req: OCRRequest,
    request: Request,
    user: dict = Depends(get_optional_user),
    db: Any | None = Depends(get_db),
):
    await enforce_endpoint_quota(request=request, user=user, db=db, scope="ocr")
    image_bytes, mime_type = _decode_image_payload(req.imageBase64)
    await reserve_ai_slot()
    try:
        model = get_gemini_model()
        response = await asyncio.to_thread(
            model.generate_content,
            [
                "Extrais tout le texte de cette image. Décris l'image s'il n'y a pas de texte. N'ajoute aucun commentaire.",
                {"mime_type": mime_type, "data": image_bytes},
            ],
            request_options={"timeout": get_settings().provider_timeout_seconds},
        )
        if not getattr(response, "text", None):
            raise RuntimeError("Le fournisseur n'a retourné aucun texte.")
        return {"response": response.text}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Le traitement OCR par le fournisseur a échoué.")
        raise HTTPException(
            status_code=502,
            detail="Le service de vision est temporairement indisponible.",
        ) from exc
    finally:
        release_ai_slot()


@router.post("/api/audio", response_model=AudioResponse)
async def audio_endpoint(
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(get_optional_user),
    db: Any | None = Depends(get_db),
):
    await enforce_endpoint_quota(request=request, user=user, db=db, scope="audio")

    mime_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if mime_type not in SUPPORTED_AUDIO_MIME:
        raise HTTPException(
            status_code=415,
            detail="Format audio non pris en charge. Utilisez WebM, MP4, WAV, OGG, AAC ou MP3.",
        )

    audio_bytes = await file.read(get_settings().max_audio_bytes + 1)
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Fichier audio vide.")
    if len(audio_bytes) > get_settings().max_audio_bytes:
        raise HTTPException(status_code=413, detail="Fichier audio trop volumineux.")
    
    await reserve_ai_slot()
    try:
        model = get_gemini_model()
        response = await asyncio.to_thread(
            model.generate_content,
            [
                "Transcris précisément et mot pour mot cet audio. N'ajoute aucun commentaire.",
                {"mime_type": mime_type, "data": audio_bytes},
            ],
            request_options={"timeout": get_settings().provider_timeout_seconds},
        )
        if not getattr(response, "text", None):
            raise RuntimeError("Le fournisseur n'a retourné aucune transcription.")
        return {"text": response.text.strip()}
    except Exception as exc:
        logger.exception("Le traitement audio par le fournisseur a échoué.")
        raise HTTPException(
            status_code=502,
            detail="Le service audio est temporairement indisponible.",
        ) from exc
    finally:
        release_ai_slot()
