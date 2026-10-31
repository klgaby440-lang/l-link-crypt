"""Collecte séparée et facultative des données d'amélioration."""

import logging
from datetime import datetime, timezone
from typing import Any

from llink_api.config import get_settings

logger = logging.getLogger(__name__)


async def record_exchange_if_consented(
    *,
    db: Any | None,
    prompt: str,
    response: str,
    user_uid: str,
    source: str,
    preferences: str | None,
    mode: str | None,
    consent: bool,
) -> None:
    """Enregistre un échange seulement avec consentement explicite et activation serveur.

    L'identifiant Firebase n'est volontairement pas copié dans le dataset.
    L'export automatique par e-mail et la commande secrète d'export ne sont pas
    repris dans cette version du socle.
    """
    settings = get_settings()
    if not settings.enable_dataset_collection or not consent:
        return
    if user_uid == "anonymous" or db is None:
        return

    document = {
        "prompt": prompt,
        "response": response,
        "preferences": preferences,
        "source": source,
        "mode": mode,
        "timestamp": datetime.now(timezone.utc),
        "consent_basis": "explicit_request",
    }
    try:
        db.collection("global_datasets").add(document)
    except Exception:
        # Une collecte facultative ne doit jamais faire échouer le chat.
        logger.exception("Échec de l'enregistrement facultatif d'un échange consenti.")
