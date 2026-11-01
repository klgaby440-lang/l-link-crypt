"""Consultation de la consommation privée de l'utilisateur."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from llink_api.database import get_db
from llink_api.schemas import UsageResponse
from llink_api.security import require_authenticated_user
from llink_api.services.entitlements import resolve_entitled_level
from llink_api.services.security_limits import enforce_endpoint_quota
from llink_api.services.usage_meter import read_current_usage

router = APIRouter()


@router.get("/api/usage", response_model=UsageResponse)
async def get_usage(
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    await enforce_endpoint_quota(
        request=request,
        user=user,
        db=db,
        scope="usage_read",
    )
    level = await asyncio.to_thread(resolve_entitled_level, user, db)
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Service de consommation temporairement indisponible.",
        )
    return await read_current_usage(db=db, uid=user["uid"], level=level)
