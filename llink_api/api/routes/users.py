"""Routes de compte, état d'abonnement et validation de paiement."""

import logging

from firebase_admin import auth as firebase_auth

from firebase_admin import auth as firebase_auth
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from llink_api.database import get_db
from llink_api.schemas import (
    PaymentVerifyResponse,
    UserStatusResponse,
    VerifyPaymentRequest,
)
from llink_api.security import get_optional_user, require_authenticated_user
from llink_api.services.security_limits import enforce_endpoint_quota

logger = logging.getLogger(__name__)
router = APIRouter()




@router.post("/api/auth/desktop-exchange")
async def exchange_desktop_firebase_token(
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    """Échange un jeton Google vérifié dans le navigateur système contre un custom token."""
    await enforce_endpoint_quota(
        request=request, user=user, db=db, scope="auth_desktop_exchange"
    )
    firebase_claims = user.get("firebase") or {}
    if not isinstance(firebase_claims, dict) or firebase_claims.get("sign_in_provider") != "google.com":
        raise HTTPException(
            status_code=403,
            detail="Cette connexion de bureau exige une authentification Google vérifiée.",
        )
    try:
        custom_token = firebase_auth.create_custom_token(
            str(user["uid"]),
            developer_claims={"llink_google_verified": True},
        )
        if isinstance(custom_token, bytes):
            custom_token = custom_token.decode("utf-8")
        if not isinstance(custom_token, str) or not custom_token:
            raise ValueError("Firebase Admin a retourné un custom token vide.")
        return {"customToken": custom_token}
    except Exception as exc:
        logger.exception("Échec de l'échange du jeton pour l'application Tauri.")
        raise HTTPException(
            status_code=503,
            detail="Impossible de finaliser la connexion Google sur cette installation.",
        ) from exc


@router.post("/api/auth/think-exchange")
async def exchange_think_sso_for_firebase(
    payload: ThinkExchangeRequest,
    request: Request,
    db: Any | None = Depends(get_db),
):
    """Convertit une identité Think vérifiée en session Firebase propre à Llink."""
    await enforce_endpoint_quota(
        request=request, user={"uid": "anonymous"}, db=db, scope="auth_think_exchange"
    )
    settings = get_settings()
    if len(settings.think_sso_secret) < 32:
        raise HTTPException(status_code=503, detail="La connexion commune Think-Llink n’est pas configurée.")
    try:
        claims = jwt.decode(
            payload.sso_token, settings.think_sso_secret, algorithms=["HS256"],
            issuer="think-api", audience="llink-api",
            options={"require": ["sub", "think_id", "email", "iat", "exp", "jti", "scope"]},
        )
        if claims.get("scope") != "llink":
            raise jwt.InvalidTokenError("scope invalide")
        think_user_id = int(claims["sub"])
        think_id = str(claims["think_id"]).strip()
        email = str(claims["email"]).strip().lower()
        full_name = str(claims.get("name") or "").strip()
        if think_user_id <= 0 or not think_id.startswith("THK-") or "@" not in email:
            raise jwt.InvalidTokenError("identité Think invalide")
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="La session Think est invalide ou expirée. Reconnecte-toi à Think.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    # UID dédié : ne jamais fusionner deux comptes par simple égalité d’adresse e-mail.
    firebase_uid = "think_" + think_id.lower()
    try:
        custom_token = firebase_auth.create_custom_token(
            firebase_uid,
            developer_claims={
                "auth_source": "think", "think_user_id": think_user_id,
                "think_id": think_id, "think_email": email, "think_name": full_name,
            },
        )
        if isinstance(custom_token, bytes):
            custom_token = custom_token.decode("utf-8")
        if not isinstance(custom_token, str) or not custom_token:
            raise ValueError("Firebase Admin a retourné un custom token vide.")
        return {
            "customToken": custom_token,
            "user": {"uid": firebase_uid, "think_id": think_id, "email": email, "full_name": full_name},
        }
    except Exception as exc:
        logger.exception("Échec de création de session Firebase pour un compte Think.")
        raise HTTPException(status_code=503, detail="Impossible de finaliser la connexion Think sur Llink.") from exc

@router.get("/api/user/status", response_model=UserStatusResponse, response_model_exclude_unset=True)
async def check_status(
    request: Request,
    user: dict = Depends(get_optional_user),
    db: Any | None = Depends(get_db),
):
    await enforce_endpoint_quota(request=request, user=user, db=db, scope="user_status")
    if user.get("uid") == "anonymous":
        return {"isValid": False, "expirationDate": None, "isNewUser": False}
    if db is None:
        raise HTTPException(status_code=503, detail="Service de compte temporairement indisponible.")

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
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    await enforce_endpoint_quota(
        request=request, user=user, db=db, scope="payment_verify"
    )
    if db is None:
        raise HTTPException(status_code=503, detail="Service de paiement temporairement indisponible.")

    # L'activation Pro reste désactivée tant que Think ne fournit pas une
    # confirmation serveur vérifiable (phase 7). Aucune référence cliente ne suffit.
    logger.info("Demande de vérification de paiement reçue ; intégration Think en attente.")
    return {"success": False}
