"""Synchronisation et restauration de l'historique cloud réservées aux comptes."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from llink_api.database import get_db
from llink_api.schemas import ChatSyncPayload, HistoryResponse, HistorySyncResponse
from llink_api.security import require_authenticated_user
from llink_api.services.security_limits import enforce_endpoint_quota

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/history/sync", response_model=HistorySyncResponse)
async def sync_history(
    chat: ChatSyncPayload,
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    await enforce_endpoint_quota(
        request=request, user=user, db=db, scope="history_sync"
    )
    if db is None:
        raise HTTPException(status_code=503, detail="Stockage de l'historique temporairement indisponible.")

    chat_data = chat.model_dump(exclude_none=True)
    sync_id = chat.syncId or str(chat_data.get("id", "temp"))
    chat_data["syncId"] = sync_id
    db.collection("users").document(user["uid"]).collection("chats").document(
        sync_id
    ).set(chat_data)
    return {"status": "success"}


@router.get("/api/history", response_model=HistoryResponse, response_model_exclude_unset=True)
async def get_history(
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    await enforce_endpoint_quota(
        request=request, user=user, db=db, scope="history_read"
    )
    if db is None:
        raise HTTPException(status_code=503, detail="Stockage de l'historique temporairement indisponible.")

    try:
        documents = (
            db.collection("users").document(user["uid"]).collection("chats").stream()
        )
        chats = []
        for document in documents:
            chat_data = document.to_dict() or {}
            chat_data.setdefault("syncId", document.id)
            chat_data["cloud_id"] = document.id
            chats.append(chat_data)
        return {"chats": chats}
    except Exception as exc:
        logger.exception("Erreur lors de la restauration de l'historique.")
        raise HTTPException(
            status_code=503,
            detail="Impossible de récupérer l'historique pour le moment.",
        ) from exc
