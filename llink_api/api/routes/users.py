"""Routes de compte et état d'abonnement."""

import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from llink_api.database import get_db
from llink_api.schemas import (
    PaymentVerifyResponse,
    UserStatusResponse,
    VerifyPaymentRequest,
)
from llink_api.security import verify_token

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/user/status", response_model=UserStatusResponse, response_model_exclude_unset=True)
async def check_status(
    user: dict = Depends(verify_token),
    db: Any | None = Depends(get_db),
):
    if user.get("uid") == "anonymous" or db is None:
        return {"isValid": False, "expirationDate": None, "isNewUser": False}

    uid = user["uid"]
    user_ref = db.collection("users").document(uid)
    document = user_ref.get()
    now = datetime.utcnow()

    if not document.exists:
        expiration = now + timedelta(days=3)
        user_data = {
            "email": user.get("email", ""),
            "trialStart": now,
            "expirationDate": expiration,
            "isPro": False,
        }
        user_ref.set(user_data)
        return {
            "isValid": True,
            "isTrial": True,
            "expirationDate": expiration.timestamp() * 1000,
            "isNewUser": True,
        }

    data = document.to_dict() or {}
    exp_date = data.get("expirationDate")
    if exp_date:
        if hasattr(exp_date, "timestamp"):
            is_active = exp_date.timestamp() > now.timestamp()
            exp_timestamp = exp_date.timestamp() * 1000
        else:
            exp_timestamp = float(exp_date) * 1000
            is_active = exp_timestamp > now.timestamp() * 1000
    else:
        is_active = False
        exp_timestamp = None

    return {
        "isValid": is_active,
        "isTrial": not data.get("isPro", False) and is_active,
        "expirationDate": exp_timestamp,
        "isNewUser": False,
    }


@router.post("/api/verify-payment", response_model=PaymentVerifyResponse)
async def verify_payment(
    req: VerifyPaymentRequest,
    user: dict = Depends(verify_token),
    db: Any | None = Depends(get_db),
):
    if user.get("uid") == "anonymous" or db is None:
        raise HTTPException(
            status_code=401,
            detail="Connectez-vous avec Google pour vous abonner.",
        )

    # Important : l'ancien mécanisme accordait Pro à partir d'une référence
    # fournie par le navigateur, sans preuve de paiement. Il est désactivé.
    # Le contrat {success: bool} reste compatible ; l'intégration réelle attend
    # une API Think qui vérifiera le statut côté serveur (phase 7).
    logger.info("Demande de vérification de paiement reçue ; intégration Think en attente.")
    return {"success": False}
