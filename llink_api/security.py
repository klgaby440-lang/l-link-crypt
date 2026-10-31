"""Authentification Firebase utilisée par les routes protégées."""

import logging
from typing import Any

from fastapi import Depends, Header
from firebase_admin import auth as firebase_auth

from llink_api.database import get_db

logger = logging.getLogger(__name__)


def verify_token(
    authorization: str | None = Header(default=None),
    db: Any | None = Depends(get_db),
) -> dict:
    """Vérifie un Firebase ID token.

    La réponse anonyme sur jeton absent/invalide est conservée temporairement
    pour ne pas casser le comportement historique du frontend. La politique
    stricte 401/403 et les autorisations détaillées appartiennent à la phase 2.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return {"uid": "anonymous"}

    if db is None:
        return {"uid": "anonymous"}

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return {"uid": "anonymous"}

    try:
        return firebase_auth.verify_id_token(token)
    except Exception:
        logger.warning("Jeton Firebase absent, invalide ou expiré.")
        return {"uid": "anonymous"}
