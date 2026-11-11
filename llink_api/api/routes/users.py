"""Routes de compte, état d’abonnement et validation de paiement."""

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from firebase_admin import auth as firebase_auth
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from llink_api.config import get_settings
from llink_api.database import get_db
from llink_api.schemas import (
    LlinkSubscriptionCheckoutRequest,
    LlinkSubscriptionRefreshRequest,
    LlinkCreditCheckoutRequest,
    PaymentVerifyResponse,
    ThinkExchangeRequest,
    UserStatusResponse,
    VerifyPaymentRequest,
)
from llink_api.security import get_optional_user, require_authenticated_user
from llink_api.services.security_limits import enforce_endpoint_quota
from llink_api.services.think_billing import (
    create_think_subscription_checkout,
    get_think_mobile_money_accounts,
    get_think_plan_catalog,
    refresh_think_subscription_payment,
    get_think_subscription,
    get_think_credit_catalog,
    create_think_credit_checkout,
    refresh_think_credit_purchase,
)

from llink_api.services.credit_wallet import read_credit_wallet, grant_verified_purchase

logger = logging.getLogger(__name__)
router = APIRouter()

_sso_jti_lock = threading.Lock()
_sso_jti_memory: dict[str, float] = {}


def _consume_think_sso_jti(db: Any | None, jti: str, uid: str, expires_at: int) -> None:
    """Empêche la réutilisation d'un ticket SSO Think pendant sa fenêtre de validité."""
    if db is None:
        if get_settings().environment not in {"development", "test"}:
            raise HTTPException(status_code=503, detail="Le stockage anti-rejeu SSO est indisponible.")
        now = time.time()
        with _sso_jti_lock:
            for key, expiry in list(_sso_jti_memory.items()):
                if expiry <= now:
                    _sso_jti_memory.pop(key, None)
            if jti in _sso_jti_memory:
                raise HTTPException(status_code=401, detail="Ce ticket SSO Think a déjà été utilisé.")
            _sso_jti_memory[jti] = float(expires_at)
        return

    try:
        from google.api_core.exceptions import AlreadyExists
        db.collection("think_sso_jti").document(jti).create({
            "firebase_uid": uid,
            "expires_at_epoch": int(expires_at),
            "used_at_epoch": int(time.time()),
        })
    except AlreadyExists:
        raise HTTPException(status_code=401, detail="Ce ticket SSO Think a déjà été utilisé.") from None
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Le ticket SSO Think n'a pas pu être consommé dans Firestore.")
        raise HTTPException(status_code=503, detail="La protection anti-rejeu SSO est indisponible.") from exc





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
    _consume_think_sso_jti(db, str(claims["jti"]), firebase_uid, int(claims["exp"]))
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
    # L'accès au compte n'expire plus avec un abonnement : la consommation
    # est désormais autorisée et facturée via le portefeuille de crédits.
    return {
        "isValid": True,
        "isTrial": False,
        "expirationDate": None,
        "isNewUser": False,
        "plan": "credits",
        "subscriptionStatus": "credits",
    }
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


@router.get("/api/credits/catalog")
async def get_llink_credit_catalog(
    request: Request,
    user: dict = Depends(require_authenticated_user),
):
    await enforce_endpoint_quota(request=request, user=user, db=get_db(), scope="subscription_status")
    return await asyncio.to_thread(get_think_credit_catalog)


@router.get("/api/credits/wallet")
async def get_llink_credit_wallet(
    request: Request,
    user: dict = Depends(require_authenticated_user),
):
    db = get_db()
    await enforce_endpoint_quota(request=request, user=user, db=db, scope="subscription_status")
    return await read_credit_wallet(db=db, uid=str(user.get("uid") or ""))


@router.post("/api/credits/checkout")
async def create_llink_credit_checkout_route(
    payload: LlinkCreditCheckoutRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: dict = Depends(require_authenticated_user),
):
    await enforce_endpoint_quota(request=request, user=user, db=get_db(), scope="subscription_checkout")
    if user.get("auth_source") != "think" or not user.get("think_user_id"):
        raise HTTPException(status_code=403, detail="Connecte-toi avec ton compte Think pour acheter des crédits.")
    checkout_id = (idempotency_key or "").strip()
    if not 8 <= len(checkout_id) <= 64 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in checkout_id):
        raise HTTPException(status_code=422, detail="Clé d'idempotence de l'achat invalide.")
    return await asyncio.to_thread(
        create_think_credit_checkout,
        think_user_id=int(user["think_user_id"]), credits=payload.credits,
        wallet_type=payload.wallet_type, payment_method=payload.payment_method,
        checkout_id=checkout_id, mobile_money_account_id=payload.mobile_money_account_id,
    )


@router.post("/api/credits/refresh")
async def refresh_llink_credit_payment(
    payload: LlinkSubscriptionRefreshRequest,
    request: Request,
    user: dict = Depends(require_authenticated_user),
):
    db = get_db()
    await enforce_endpoint_quota(request=request, user=user, db=db, scope="subscription_checkout")
    if user.get("auth_source") != "think" or not user.get("think_user_id"):
        raise HTTPException(status_code=403, detail="Connecte-toi avec ton compte Think pour vérifier le paiement.")
    result = await asyncio.to_thread(
        refresh_think_credit_purchase,
        think_user_id=int(user["think_user_id"]), public_id=payload.public_id,
    )
    credit_info = result.get("credits") or {}
    granted = None
    if result.get("payment_status") == "accepted" and credit_info.get("status") == "paid":
        granted = await grant_verified_purchase(
            db=db, uid=str(user.get("uid") or ""), public_id=payload.public_id,
            credits=int(credit_info.get("purchased") or 0),
            wallet_type=str(credit_info.get("wallet_type") or "online"),
        )
    wallet = await read_credit_wallet(db=db, uid=str(user.get("uid") or ""))
    return {"product": "llink", **result, "grant": granted, "wallet": wallet}


@router.get("/api/subscriptions/status")
async def get_llink_subscription_status(
    request: Request,
    user: dict = Depends(require_authenticated_user),
):
    await enforce_endpoint_quota(
        request=request, user=user, db=get_db(), scope="subscription_status"
    )
    if user.get("auth_source") != "think" or not user.get("think_user_id"):
        raise HTTPException(status_code=403, detail="Les abonnements Llink sont gérés par le compte commun Think.")
    result = await asyncio.to_thread(get_think_subscription, int(user["think_user_id"]))
    return {"product": "llink", **result}


@router.get("/api/subscriptions/catalog")
async def get_llink_subscription_catalog(
    request: Request,
    user: dict = Depends(require_authenticated_user),
):
    await enforce_endpoint_quota(
        request=request, user=user, db=get_db(), scope="subscription_status"
    )
    if user.get("auth_source") != "think" or not user.get("think_user_id"):
        raise HTTPException(status_code=403, detail="Connecte-toi avec ton compte Think pour consulter les offres.")
    return await asyncio.to_thread(get_think_plan_catalog)

@router.get("/api/subscriptions/payment-options")
async def get_llink_payment_options(
    request: Request,
    user: dict = Depends(require_authenticated_user),
):
    await enforce_endpoint_quota(
        request=request, user=user, db=get_db(), scope="subscription_status"
    )
    if user.get("auth_source") != "think" or not user.get("think_user_id"):
        raise HTTPException(status_code=403, detail="Connecte-toi avec ton compte Think pour utiliser tes numéros enregistrés.")
    items = await asyncio.to_thread(get_think_mobile_money_accounts, int(user["think_user_id"]))
    return {"items": items}

@router.post("/api/subscriptions/refresh")
async def refresh_llink_subscription_payment(
    payload: LlinkSubscriptionRefreshRequest,
    request: Request,
    user: dict = Depends(require_authenticated_user),
):
    await enforce_endpoint_quota(
        request=request, user=user, db=get_db(), scope="subscription_checkout"
    )
    if user.get("auth_source") != "think" or not user.get("think_user_id"):
        raise HTTPException(status_code=403, detail="Connecte-toi avec ton compte Think pour vérifier le paiement.")
    result = await asyncio.to_thread(
        refresh_think_subscription_payment,
        think_user_id=int(user["think_user_id"]),
        public_id=payload.public_id,
    )
    return {"product": "llink", **result}

@router.post("/api/subscriptions/checkout")
async def create_llink_subscription_checkout(
    payload: LlinkSubscriptionCheckoutRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: dict = Depends(require_authenticated_user),
):
    await enforce_endpoint_quota(
        request=request, user=user, db=get_db(), scope="subscription_checkout"
    )
    if user.get("auth_source") != "think" or not user.get("think_user_id"):
        raise HTTPException(status_code=403, detail="Connecte-toi avec ton compte Think pour souscrire à Llink.")
    checkout_id = (idempotency_key or "").strip()
    if not 8 <= len(checkout_id) <= 64 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in checkout_id):
        raise HTTPException(status_code=422, detail="Clé d’idempotence de souscription invalide.")
    result = await asyncio.to_thread(
        create_think_subscription_checkout,
        think_user_id=int(user["think_user_id"]),
        plan=payload.plan,
        payment_method=payload.payment_method,
        checkout_id=checkout_id,
        mobile_money_account_id=payload.mobile_money_account_id,
    )
    return result

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
