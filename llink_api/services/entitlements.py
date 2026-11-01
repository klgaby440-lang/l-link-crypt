"""Résolution des droits à partir des données serveur Firestore."""

import time
from typing import Any

from fastapi import HTTPException

from llink_api.services.model_registry import PLAN_TO_LEVEL


def _expiration_epoch(value: Any) -> float | None:
    if value is None:
        return None
    if hasattr(value, "timestamp"):
        return float(value.timestamp())
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    # L'interface historique stockait parfois les dates en millisecondes.
    return numeric / 1000 if numeric > 10_000_000_000 else numeric


def resolve_entitled_level(user: dict, db: Any | None) -> str:
    """Le niveau demandé par le navigateur ne constitue jamais une preuve d'abonnement."""
    uid = user.get("uid", "anonymous")
    if uid == "anonymous":
        return "velora"
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Impossible de vérifier votre abonnement pour le moment.",
        )

    try:
        snapshot = db.collection("users").document(uid).get()
        data = (snapshot.to_dict() or {}) if snapshot.exists else {}
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Impossible de vérifier votre abonnement pour le moment.",
        ) from exc

    if not data.get("isPro"):
        return "velora"
    expiration = _expiration_epoch(data.get("expirationDate"))
    if expiration is None or expiration <= time.time():
        return "velora"

    # Champ canonique prévu pour l'activation après confirmation Think (phase 7).
    # Les anciens documents sans plan explicite restent limités à VELORA.
    plan = str(data.get("subscriptionPlan", "")).strip().lower()
    return PLAN_TO_LEVEL.get(plan, "velora")
