"""Synchronisation et restauration de l'historique cloud."""

import logging
from typing import Any

from fastapi import APIRouter, Depends

from llink_api.database import get_db
from llink_api.schemas import ChatSyncPayload, HistoryResponse, HistorySyncResponse
from llink_api.security import verify_token

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/history/sync", response_model=HistorySyncResponse)
async def sync_history(
    chat: ChatSyncPayload,
    user: dict = Depends(verify_token),
    db: Any | None = Depends(get_db),
):
    if user.get("uid") == "anonymous" or db is None:
        return {"status": "skipped"}

    chat_data = chat.model_dump(exclude_none=True)
    db.collection("users").document(user["uid"]).collection("chats").document(
        str(chat_data.get("id", "temp"))
    ).set(chat_data)
    return {"status": "success"}


@router.get("/api/history", response_model=HistoryResponse, response_model_exclude_unset=True)
async def get_history(
    user: dict = Depends(verify_token),
    db: Any | None = Depends(get_db),
):
    if user.get("uid") == "anonymous":
        return {"chats": []}
    if db is None:
        return {"chats": [], "warning": "Base de données hors ligne."}

    try:
        documents = (
            db.collection("users").document(user["uid"]).collection("chats").stream()
        )
        return {"chats": [document.to_dict() for document in documents]}
    except Exception as exc:
        logger.exception("Erreur lors de la restauration de l'historique.")
        return {"chats": [], "warning": f"Erreur DB: {exc}"}
