"""Routes image/OCR et audio."""

import base64
import logging

from fastapi import APIRouter, File, UploadFile

from llink_api.providers.gemini import get_gemini_model
from llink_api.schemas import AudioResponse, OCRRequest, OCRResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/ocr", response_model=OCRResponse)
async def ocr_endpoint(req: OCRRequest):
    try:
        encoded_data = req.imageBase64.split(",", 1)[1] if "," in req.imageBase64 else req.imageBase64
        image_bytes = base64.b64decode(encoded_data, validate=True)
        model = get_gemini_model()
        response = model.generate_content(
            [
                "Extrais tout le texte de cette image. Décris l'image s'il n'y a pas de texte. N'ajoute aucun commentaire.",
                {"mime_type": "image/jpeg", "data": image_bytes},
            ]
        )
        return {"response": response.text}
    except Exception as exc:
        logger.exception("Erreur de traitement OCR.")
        return {"response": f"Erreur Vision : {exc}"}


@router.post("/api/audio", response_model=AudioResponse)
async def audio_endpoint(file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read()
        model = get_gemini_model()
        response = model.generate_content(
            [
                "Transcris précisément et mot pour mot cet audio. N'ajoute aucun commentaire.",
                {"mime_type": file.content_type or "audio/webm", "data": audio_bytes},
            ]
        )
        return {"text": response.text.strip()}
    except Exception as exc:
        logger.exception("Erreur de traitement audio.")
        return {"text": f"Erreur Audio : {exc}"}
