"""Authentification Firebase stricte pour les routes cloud."""

import logging

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import exceptions as firebase_exceptions
from fastapi import Depends, Header, HTTPException, status

logger = logging.getLogger(__name__)
ANONYMOUS_USER = {"uid": "anonymous"}


def _decode_firebase_token(token: str) -> dict:
    """Vérifie signature, expiration, projet Firebase, révocation et état du compte."""
    try:
        firebase_admin.get_app()
    except ValueError as exc:
        logger.error("Firebase Admin n'est pas initialisé ; authentification indisponible.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service d'authentification temporairement indisponible.",
        ) from exc

    try:
        claims = firebase_auth.verify_id_token(token, check_revoked=True)
    except (
        firebase_auth.InvalidIdTokenError,
        firebase_auth.ExpiredIdTokenError,
        firebase_auth.RevokedIdTokenError,
        firebase_auth.UserDisabledError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton Firebase invalide ou expiré. Reconnectez-vous.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except firebase_exceptions.FirebaseError as exc:
        logger.warning("Le service Firebase n'a pas pu vérifier le jeton.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vérification d'identité indisponible. Réessayez.",
        ) from exc
    except Exception as exc:
        logger.exception("Erreur inattendue pendant la vérification Firebase.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vérification d'identité indisponible. Réessayez.",
        ) from exc

    if not isinstance(claims, dict) or not claims.get("uid"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identité Firebase invalide.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


def get_optional_user(
    authorization: str | None = Header(default=None),
) -> dict:
    """Accepte l'absence de jeton pour les fonctions anonymes, jamais un faux jeton."""
    if authorization is None or not authorization.strip():
        return ANONYMOUS_USER

    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="En-tête Authorization invalide. Utilisez Bearer <Firebase ID token>.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _decode_firebase_token(token.strip())


def require_authenticated_user(user: dict = Depends(get_optional_user)) -> dict:
    """Refuse explicitement les sessions anonymes sur les routes privées."""
    if user.get("uid") == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Connectez-vous pour accéder à cette fonction.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# Alias temporaire pour les extensions internes qui importeraient encore l'ancien nom.
verify_token = get_optional_user
