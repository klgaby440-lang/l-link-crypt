"""Initialisation et accès à Firestore."""

import json
import logging
from typing import Any

import firebase_admin
from firebase_admin import credentials, firestore

from llink_api.config import get_settings

logger = logging.getLogger(__name__)


def initialize_firestore() -> Any | None:
    """Initialise Firebase une seule fois ; l'API reste démarrable sans Firebase."""
    raw_config = get_settings().firebase_config
    if not raw_config:
        logger.warning("FIREBASE_CONFIG absent : Firestore n'est pas connecté.")
        return None

    try:
        service_account = json.loads(raw_config.strip())
        if not firebase_admin._apps:
            credential = credentials.Certificate(service_account)
            firebase_admin.initialize_app(credential)
        return firestore.client()
    except Exception:
        logger.exception("Impossible d'initialiser Firebase/Firestore.")
        return None


_db = initialize_firestore()


def get_db() -> Any | None:
    """Dépendance FastAPI partagée par les routes qui utilisent Firestore."""
    return _db
