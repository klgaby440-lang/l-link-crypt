"""Client serveur-à-serveur pour les droits et checkouts Llink gérés par Think."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from llink_api.config import get_settings


def _think_headers() -> dict[str, str]:
    settings = get_settings()
    if len(settings.think_service_token) < 32:
        raise HTTPException(
            status_code=503,
            detail="La liaison sécurisée entre Think et Llink n'est pas configurée.",
        )
    return {"X-LLINK-SERVICE-TOKEN": settings.think_service_token}


def get_think_subscription(think_user_id: int) -> dict[str, Any]:
    """Lit l'abonnement Llink depuis Think, qui reste la source de vérité."""
    settings = get_settings()
    try:
        response = httpx.get(
            f"{settings.think_api_base_url}/api/internal/llink/users/{int(think_user_id)}/subscription",
            headers=_think_headers(),
            timeout=8.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="Le service d'abonnement Think est temporairement indisponible.",
        ) from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code != 200:
        raise HTTPException(
            status_code=503 if response.status_code >= 500 else response.status_code,
            detail=payload.get("detail") or "Impossible de vérifier l'abonnement Think.",
        )
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Réponse d'abonnement Think invalide.")
    return payload


def create_think_subscription_checkout(
    *,
    think_user_id: int,
    plan: str,
    payment_method: str,
    checkout_id: str,
    mobile_money_account_id: int | None = None,
) -> dict[str, Any]:
    """Demande à Think de créer le paiement ; Llink ne transmet jamais de montant."""
    settings = get_settings()
    idempotency_key = f"llink-{int(think_user_id)}-{checkout_id}"
    try:
        response = httpx.post(
            f"{settings.think_api_base_url}/api/internal/llink/subscriptions/checkout",
            headers={**_think_headers(), "Idempotency-Key": idempotency_key},
            json={
                "think_user_id": int(think_user_id),
                "plan": plan,
                "payment_method": payment_method,
                "checkout_id": checkout_id,
                "mobile_money_account_id": mobile_money_account_id,
            },
            timeout=35.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="Impossible de contacter Think pour préparer le paiement.",
        ) from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code < 200 or response.status_code >= 300:
        status_code = response.status_code if 400 <= response.status_code < 500 else 503
        raise HTTPException(
            status_code=status_code,
            detail=payload.get("detail") or "Think n'a pas pu préparer le paiement Llink.",
        )
    if not isinstance(payload, dict) or not payload.get("public_id"):
        raise HTTPException(status_code=502, detail="Think a retourné une réponse de paiement incomplète.")
    return payload



def get_think_mobile_money_accounts(think_user_id: int) -> list[dict[str, Any]]:
    """Renvoie uniquement les numéros masqués déjà enregistrés dans Think."""
    settings = get_settings()
    try:
        response = httpx.get(
            f"{settings.think_api_base_url}/api/internal/llink/users/{int(think_user_id)}/mobile-money-accounts",
            headers=_think_headers(),
            timeout=8.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="Impossible de charger les numéros Mobile Money de Think.",
        ) from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code != 200:
        raise HTTPException(
            status_code=503 if response.status_code >= 500 else response.status_code,
            detail=payload.get("detail") or "Impossible de charger les numéros Mobile Money.",
        )
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise HTTPException(status_code=502, detail="Réponse des numéros Think invalide.")
    return [item for item in items if isinstance(item, dict)]





def get_think_plan_catalog() -> dict[str, Any]:
    """Lit les tarifs CDF configurés dans Think ; Llink ne maintient aucun prix de référence."""
    settings = get_settings()
    try:
        response = httpx.get(
            f"{settings.think_api_base_url}/api/llink/plans",
            headers=_think_headers(),
            timeout=8.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="Le catalogue des abonnements Think est temporairement indisponible.",
        ) from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code != 200:
        raise HTTPException(
            status_code=503 if response.status_code >= 500 else response.status_code,
            detail=payload.get("detail") or "Impossible de charger les tarifs Llink.",
        )
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise HTTPException(status_code=502, detail="Catalogue Llink retourné par Think invalide.")
    return payload


