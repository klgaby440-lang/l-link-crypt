"""Résolution des droits à partir des données serveur Firestore."""

import time
from typing import Any

from fastapi import HTTPException

from llink_api.services.model_registry import PLAN_TO_LEVEL
from llink_api.services.think_billing import get_think_subscription


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
    """Les modèles sont accessibles selon le portefeuille, plus selon un abonnement."""
    uid = str(user.get("uid") or "anonymous")
    if uid == "anonymous":
        return "velora"
    # Le contrôle financier est effectué avant chaque requête IA par usage_meter.
    # OMNIS ici représente le plafond d'accès aux modèles, pas un forfait payant.
    return "omnis"
