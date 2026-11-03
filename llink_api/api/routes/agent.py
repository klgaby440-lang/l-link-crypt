"""Point d'entrée explicite du nouvel agent Llink Work."""

from typing import Any

from fastapi import APIRouter, Depends, Request

from llink_api.database import get_db
from llink_api.schemas import ChatPayload
from llink_api.security import get_optional_user
from llink_api.services.work_agent import work_agent_response

router = APIRouter()


@router.post("/api/work/agent")
async def run_work_agent(
    payload: ChatPayload,
    request: Request,
    user: dict = Depends(get_optional_user),
    db: Any | None = Depends(get_db),
):
    payload.mode = "work"
    return await work_agent_response(payload, request, user, db)
