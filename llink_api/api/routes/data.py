"""Export et suppression des données personnelles Llink."""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from firebase_admin import auth as firebase_auth

from llink_api.database import get_db
from llink_api.schemas import AccountDeletionRequest
from llink_api.security import require_authenticated_user
from llink_api.services.security_limits import (
    delete_user_rate_limit_records,
    enforce_endpoint_quota,
)

logger = logging.getLogger(__name__)
router = APIRouter()

LEGACY_DATASET_OWNER_FIELDS = ("uid", "user_uid", "user_id", "userId")
ACCOUNT_REAUTH_MAX_AGE_SECONDS = 600


def _json_value(value: Any) -> Any:
    """Convertit les types Firestore en valeurs JSON sans exposer d'objet interne."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        import base64

        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    path = getattr(value, "path", None)
    if isinstance(path, str):
        return {"document_path": path}
    return str(value)


def _export_document_tree(document_ref: Any, depth: int = 0) -> dict[str, Any]:
    """Lit un document et toutes ses sous-collections, sans sortir de son arbre."""
    if depth > 12:
        raise RuntimeError("Profondeur Firestore inattendue pendant l'export.")
    snapshot = document_ref.get()
    result = dict(snapshot.to_dict() or {}) if snapshot.exists else {}
    result["_document_id"] = document_ref.id

    for collection_ref in document_ref.collections():
        result[collection_ref.id] = [
            _export_document_tree(child.reference, depth + 1)
            for child in collection_ref.stream()
        ]
    return _json_value(result)


def _legacy_dataset_documents(db: Any, uid: str) -> list[dict[str, Any]]:
    """Retrouve les anciens échanges encore explicitement liés à un UID."""
    found: dict[str, Any] = {}
    collection = db.collection("global_datasets")
    for field in LEGACY_DATASET_OWNER_FIELDS:
        query = collection.where(field, "==", uid)
        for document in query.stream():
            found[document.id] = {
                "_document_id": document.id,
                **(document.to_dict() or {}),
            }
    return _json_value(list(found.values()))


def _delete_legacy_dataset_documents(db: Any, uid: str) -> int:
    """Efface les anciens documents d'amélioration qui contiennent encore l'UID."""
    found: dict[str, Any] = {}
    collection = db.collection("global_datasets")
    for field in LEGACY_DATASET_OWNER_FIELDS:
        query = collection.where(field, "==", uid)
        for document in query.stream():
            found[document.id] = document.reference
    for reference in found.values():
        reference.delete()
    return len(found)


def _delete_document_tree(document_ref: Any, depth: int = 0) -> int:
    """Supprime récursivement les sous-collections puis le document parent."""
    if depth > 12:
        raise RuntimeError("Profondeur Firestore inattendue pendant la suppression.")
    deleted = 0
    for collection_ref in document_ref.collections():
        for child in collection_ref.stream():
            deleted += _delete_document_tree(child.reference, depth + 1)

    snapshot = document_ref.get()
    if snapshot.exists:
        document_ref.delete()
        deleted += 1
    return deleted


@router.get("/api/data/export")
async def export_personal_data(
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    """Télécharge le compte, l'historique cloud et les données d'usage du compte."""
    await enforce_endpoint_quota(
        request=request, user=user, db=db, scope="data_export"
    )
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Export indisponible : stockage des données temporairement inaccessible.",
        )

    uid = user["uid"]
    try:
        account = _export_document_tree(db.collection("users").document(uid))
        legacy_records = _legacy_dataset_documents(db, uid)
    except Exception as exc:
        logger.exception("Échec de la préparation d'un export de données personnelles.")
        raise HTTPException(
            status_code=503,
            detail="Impossible de préparer l'export complet pour le moment.",
        ) from exc

    payload = {
        "format": "llink-personal-data-export",
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": account,
        "legacy_linked_dataset_records": legacy_records,
        "notes": [
            "Les données de l'appareil sont ajoutées par l'application au téléchargement.",
            "Les anciens enregistrements anonymisés sans identifiant de propriétaire ne peuvent pas être rattachés à un compte.",
            "Les données du registre global anonyme ne sont pas des données personnelles exportables par un compte.",
        ],
    }
    filename = f"llink-data-export-{datetime.now(timezone.utc):%Y%m%d}.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


@router.delete("/api/account")
async def delete_account_and_personal_data(
    payload: AccountDeletionRequest,
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    """Supprime les données Firestore liées au compte puis le compte Firebase Auth."""
    if payload.confirmation != "SUPPRIMER MON COMPTE":
        raise HTTPException(status_code=422, detail="Confirmation de suppression invalide.")

    auth_time = user.get("auth_time")
    now = time.time()
    try:
        age = now - float(auth_time)
    except (TypeError, ValueError):
        age = ACCOUNT_REAUTH_MAX_AGE_SECONDS + 1
    if age < -60 or age > ACCOUNT_REAUTH_MAX_AGE_SECONDS:
        raise HTTPException(
            status_code=401,
            detail=(
                "Une connexion récente est nécessaire. Déconnectez-vous puis "
                "reconnectez-vous avant de confirmer la suppression du compte."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    await enforce_endpoint_quota(
        request=request, user=user, db=db, scope="account_delete"
    )
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Suppression indisponible : stockage des données temporairement inaccessible.",
        )

    uid = user["uid"]
    try:
        # Le parcours est idempotent : une nouvelle tentative peut terminer
        # le nettoyage si une étape précédente a échoué.
        deleted_account_documents = _delete_document_tree(
            db.collection("users").document(uid)
        )
        deleted_legacy_records = _delete_legacy_dataset_documents(db, uid)
        deleted_quota_records = delete_user_rate_limit_records(db, uid)
        try:
            firebase_auth.delete_user(uid)
        except firebase_auth.UserNotFoundError:
            pass
    except Exception as exc:
        logger.exception("Suppression incomplète des données d'un compte Llink.")
        raise HTTPException(
            status_code=503,
            detail=(
                "La suppression n'a pas pu être terminée. Réessayez ; "
                "les opérations déjà réalisées ne seront pas recréées."
            ),
        ) from exc

    return {
        "status": "deleted",
        "deleted_documents": deleted_account_documents,
        "deleted_legacy_records": deleted_legacy_records,
        "deleted_quota_records": deleted_quota_records,
    }
