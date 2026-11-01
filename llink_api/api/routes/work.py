"""Tool Engine Work : projets et fichiers isolés par utilisateur."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from google.cloud import firestore as google_firestore
from pydantic import BaseModel, Field

from llink_api.database import get_db
from llink_api.security import require_authenticated_user
from llink_api.services.security_limits import enforce_endpoint_quota

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_FILE_BYTES = 700_000
MAX_PROJECTS_PER_USER = 100
MAX_FILES_PER_USER = 500
MAX_FILE_VERSIONS = 20
_SAFE_ID = re.compile(r"^[a-f0-9]{32}$")


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class WorkFileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    folder: str = Field(default="", max_length=300)
    content: str = Field(default="", max_length=MAX_FILE_BYTES)
    language: str = Field(default="plaintext", min_length=1, max_length=40)
    project_id: str | None = Field(default=None, max_length=32)


class WorkFileUpdate(BaseModel):
    content: str = Field(max_length=MAX_FILE_BYTES)
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=180)
    folder: str | None = Field(default=None, max_length=300)
    language: str | None = Field(default=None, min_length=1, max_length=40)


class RestoreVersionRequest(BaseModel):
    version: int = Field(ge=1)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_firestore(db: Any | None) -> Any:
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Le stockage Work est temporairement indisponible.",
        )
    return db


def _validate_id(value: str) -> str:
    normalized = (value or "").strip().lower()
    if not _SAFE_ID.fullmatch(normalized):
        raise HTTPException(status_code=404, detail="Ressource Work introuvable.")
    return normalized


def normalize_file_name(name: str) -> str:
    value = (name or "").strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise HTTPException(status_code=422, detail="Nom de fichier invalide.")
    if any(ord(char) < 32 for char in value):
        raise HTTPException(status_code=422, detail="Le nom de fichier contient des caractères interdits.")
    return value


def normalize_folder(folder: str) -> str:
    value = (folder or "").replace("\\", "/").strip("/")
    if not value:
        return ""
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(status_code=422, detail="Chemin de dossier invalide.")
    if any(any(ord(char) < 32 for char in part) for part in parts):
        raise HTTPException(status_code=422, detail="Le chemin contient des caractères interdits.")
    return "/".join(parts)


def file_path(folder: str, name: str) -> str:
    safe_name = normalize_file_name(name)
    safe_folder = normalize_folder(folder)
    return f"{safe_folder}/{safe_name}" if safe_folder else safe_name


def validate_content_size(content: str) -> None:
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Un fichier Work ne peut pas dépasser {MAX_FILE_BYTES // 1000} Ko.",
        )


def _user_collection(db: Any, uid: str, name: str):
    return db.collection("users").document(uid).collection(name)


def _serialize(snapshot: Any, include_content: bool = True) -> dict[str, Any]:
    data = snapshot.to_dict() or {}
    result = {
        "id": snapshot.id,
        "name": data.get("name", ""),
        "folder": data.get("folder", ""),
        "path": data.get("path", ""),
        "language": data.get("language", "plaintext"),
        "project_id": data.get("project_id"),
        "version": int(data.get("version", 1)),
        "size_bytes": int(data.get("size_bytes", 0)),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "sync_status": "cloud",
    }
    if include_content:
        result["content"] = data.get("content", "")
    return result


async def _quota(request: Request, user: dict, db: Any, scope: str) -> None:
    await enforce_endpoint_quota(request=request, user=user, db=db, scope=scope)


async def _ensure_project(db: Any, uid: str, project_id: str | None) -> None:
    if not project_id:
        return
    project_id = _validate_id(project_id)
    snapshot = await asyncio.to_thread(
        _user_collection(db, uid, "work_projects").document(project_id).get
    )
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Projet Work introuvable.")


@router.get("/api/work/projects")
async def list_projects(
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    db = _require_firestore(db)
    await _quota(request, user, db, "work_read")
    collection = _user_collection(db, user["uid"], "work_projects")
    try:
        snapshots = await asyncio.to_thread(lambda: list(collection.stream()))
        projects = []
        for snapshot in snapshots:
            data = snapshot.to_dict() or {}
            projects.append({
                "id": snapshot.id,
                "name": data.get("name", ""),
                "description": data.get("description", ""),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
            })
        projects.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return {"projects": projects}
    except Exception as exc:
        logger.exception("Impossible de lister les projets Work.")
        raise HTTPException(status_code=503, detail="Impossible de récupérer les projets Work.") from exc


@router.post("/api/work/projects", status_code=201)
async def create_project(
    payload: ProjectCreate,
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    db = _require_firestore(db)
    await _quota(request, user, db, "work_write")
    collection = _user_collection(db, user["uid"], "work_projects")
    try:
        existing = await asyncio.to_thread(lambda: list(collection.stream()))
        if len(existing) >= MAX_PROJECTS_PER_USER:
            raise HTTPException(status_code=413, detail="Limite de projets Work atteinte.")
        project_id = uuid.uuid4().hex
        now = utc_now()
        data = {
            "name": payload.name.strip(),
            "description": payload.description.strip(),
            "created_at": now,
            "updated_at": now,
        }
        await asyncio.to_thread(collection.document(project_id).set, data)
        return {"id": project_id, **data}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Impossible de créer un projet Work.")
        raise HTTPException(status_code=503, detail="Impossible de créer le projet Work.") from exc


@router.patch("/api/work/projects/{project_id}")
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    db = _require_firestore(db)
    await _quota(request, user, db, "work_write")
    project_id = _validate_id(project_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="Aucune modification fournie.")
    if "name" in updates and updates["name"] is not None:
        updates["name"] = updates["name"].strip()
    updates["updated_at"] = utc_now()
    reference = _user_collection(db, user["uid"], "work_projects").document(project_id)
    try:
        snapshot = await asyncio.to_thread(reference.get)
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail="Projet Work introuvable.")
        await asyncio.to_thread(reference.update, updates)
        return {"id": project_id, **(snapshot.to_dict() or {}), **updates}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Impossible de modifier un projet Work.")
        raise HTTPException(status_code=503, detail="Impossible de modifier le projet Work.") from exc


@router.delete("/api/work/projects/{project_id}")
async def delete_project(
    project_id: str,
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    db = _require_firestore(db)
    await _quota(request, user, db, "work_delete")
    project_id = _validate_id(project_id)
    projects = _user_collection(db, user["uid"], "work_projects")
    files = _user_collection(db, user["uid"], "work_files")
    reference = projects.document(project_id)
    try:
        snapshot = await asyncio.to_thread(reference.get)
        if not snapshot.exists:
            return {"deleted": False, "project_id": project_id}
        linked = await asyncio.to_thread(
            lambda: list(files.where("project_id", "==", project_id).stream())
        )
        for offset in range(0, len(linked), 400):
            batch = db.batch()
            for document in linked[offset:offset + 400]:
                batch.update(document.reference, {"project_id": None, "updated_at": utc_now()})
            await asyncio.to_thread(batch.commit)
        await asyncio.to_thread(reference.delete)
        return {"deleted": True, "project_id": project_id, "unlinked_files": len(linked)}
    except Exception as exc:
        logger.exception("Impossible de supprimer un projet Work.")
        raise HTTPException(status_code=503, detail="Impossible de supprimer le projet Work.") from exc


@router.get("/api/work/files")
async def list_files(
    request: Request,
    project_id: str | None = None,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    db = _require_firestore(db)
    await _quota(request, user, db, "work_read")
    collection = _user_collection(db, user["uid"], "work_files")
    try:
        if project_id:
            project_id = _validate_id(project_id)
            await _ensure_project(db, user["uid"], project_id)
            snapshots = await asyncio.to_thread(
                lambda: list(collection.where("project_id", "==", project_id).stream())
            )
        else:
            snapshots = await asyncio.to_thread(lambda: list(collection.stream()))
        items = [_serialize(snapshot, include_content=False) for snapshot in snapshots]
        items.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return {"files": items}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Impossible de lister les fichiers Work.")
        raise HTTPException(status_code=503, detail="Impossible de récupérer les fichiers Work.") from exc


@router.post("/api/work/files", status_code=201)
async def create_file(
    payload: WorkFileCreate,
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    db = _require_firestore(db)
    await _quota(request, user, db, "work_write")
    validate_content_size(payload.content)
    await _ensure_project(db, user["uid"], payload.project_id)
    collection = _user_collection(db, user["uid"], "work_files")
    try:
        existing = await asyncio.to_thread(lambda: list(collection.stream()))
        if len(existing) >= MAX_FILES_PER_USER:
            raise HTTPException(status_code=413, detail="Limite de fichiers Work atteinte.")
        name = normalize_file_name(payload.name)
        folder = normalize_folder(payload.folder)
        path = file_path(folder, name)
        duplicate = await asyncio.to_thread(
            lambda: list(collection.where("path", "==", path).limit(1).stream())
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Un fichier existe déjà à cet emplacement.")
        file_id = uuid.uuid4().hex
        now = utc_now()
        data = {
            "name": name,
            "folder": folder,
            "path": path,
            "language": payload.language,
            "project_id": payload.project_id,
            "content": payload.content,
            "size_bytes": len(payload.content.encode("utf-8")),
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }
        reference = collection.document(file_id)
        await asyncio.to_thread(reference.set, data)
        await asyncio.to_thread(
            reference.collection("versions").document("1").set,
            {
                "version": 1,
                "content": payload.content,
                "created_at": now,
                "size_bytes": data["size_bytes"],
            },
        )
        return {"id": file_id, **data, "sync_status": "cloud"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Impossible de créer un fichier Work.")
        raise HTTPException(status_code=503, detail="Impossible d'enregistrer le fichier Work.") from exc


@router.get("/api/work/files/{file_id}")
async def get_file(
    file_id: str,
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    db = _require_firestore(db)
    await _quota(request, user, db, "work_read")
    file_id = _validate_id(file_id)
    reference = _user_collection(db, user["uid"], "work_files").document(file_id)
    try:
        snapshot = await asyncio.to_thread(reference.get)
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail="Fichier Work introuvable.")
        return _serialize(snapshot)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Impossible de lire un fichier Work.")
        raise HTTPException(status_code=503, detail="Impossible de lire le fichier Work.") from exc


@router.put("/api/work/files/{file_id}")
async def update_file(
    file_id: str,
    payload: WorkFileUpdate,
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    db = _require_firestore(db)
    await _quota(request, user, db, "work_write")
    file_id = _validate_id(file_id)
    validate_content_size(payload.content)
    collection = _user_collection(db, user["uid"], "work_files")
    reference = collection.document(file_id)
    now = utc_now()
    updates = {
        "content": payload.content,
        "size_bytes": len(payload.content.encode("utf-8")),
        "updated_at": now,
        "version": payload.expected_version + 1,
    }
    if payload.name is not None:
        updates["name"] = normalize_file_name(payload.name)
    if payload.folder is not None:
        updates["folder"] = normalize_folder(payload.folder)
    if payload.language is not None:
        updates["language"] = payload.language
    updates["path"] = file_path(
        updates.get("folder", ""),
        updates.get("name", ""),
    )

    @google_firestore.transactional
    def apply_update(transaction):
        snapshot = reference.get(transaction=transaction)
        if not snapshot.exists:
            return "missing", None
        current = snapshot.to_dict() or {}
        current_version = int(current.get("version", 1))
        if current_version != payload.expected_version:
            return "conflict", current
        old_version_ref = reference.collection("versions").document(str(current_version))
        transaction.set(
            old_version_ref,
            {
                "version": current_version,
                "content": current.get("content", ""),
                "created_at": current.get("updated_at") or current.get("created_at") or now,
                "size_bytes": int(current.get("size_bytes", 0)),
            },
        )
        transaction.update(reference, updates)
        return "ok", {**current, **updates}

    try:
        status, result = await asyncio.to_thread(apply_update, db.transaction())
        if status == "missing":
            raise HTTPException(status_code=404, detail="Fichier Work introuvable.")
        if status == "conflict":
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Ce fichier a été modifié ailleurs.",
                    "current_version": int(result.get("version", 1)),
                },
            )
        versions = reference.collection("versions")
        old_versions = await asyncio.to_thread(lambda: list(versions.stream()))
        if len(old_versions) > MAX_FILE_VERSIONS:
            for snapshot in old_versions[:len(old_versions) - MAX_FILE_VERSIONS]:
                await asyncio.to_thread(snapshot.reference.delete)
        return {"id": file_id, **result, "sync_status": "cloud"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Impossible de mettre à jour un fichier Work.")
        raise HTTPException(status_code=503, detail="Impossible d'enregistrer les modifications.") from exc


@router.get("/api/work/files/{file_id}/versions")
async def list_file_versions(
    file_id: str,
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    db = _require_firestore(db)
    await _quota(request, user, db, "work_read")
    file_id = _validate_id(file_id)
    reference = _user_collection(db, user["uid"], "work_files").document(file_id)
    try:
        current = await asyncio.to_thread(reference.get)
        if not current.exists:
            raise HTTPException(status_code=404, detail="Fichier Work introuvable.")
        snapshots = await asyncio.to_thread(
            lambda: list(reference.collection("versions").stream())
        )
        current_data = current.to_dict() or {}
        versions = [{
            "version": int(snapshot.to_dict().get("version", snapshot.id)),
            "created_at": (snapshot.to_dict() or {}).get("created_at"),
            "size_bytes": int((snapshot.to_dict() or {}).get("size_bytes", 0)),
            "is_current": False,
        } for snapshot in snapshots]
        versions.append({
            "version": int(current_data.get("version", 1)),
            "created_at": current_data.get("updated_at") or current_data.get("created_at"),
            "size_bytes": int(current_data.get("size_bytes", 0)),
            "is_current": True,
        })
        versions.sort(key=lambda item: item["version"], reverse=True)
        return {"versions": versions[:MAX_FILE_VERSIONS]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Impossible de lire les versions Work.")
        raise HTTPException(status_code=503, detail="Impossible de récupérer les versions.") from exc


@router.post("/api/work/files/{file_id}/restore")
async def restore_file_version(
    file_id: str,
    payload: RestoreVersionRequest,
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    db = _require_firestore(db)
    await _quota(request, user, db, "work_write")
    file_id = _validate_id(file_id)
    reference = _user_collection(db, user["uid"], "work_files").document(file_id)
    try:
        version_ref = reference.collection("versions").document(str(payload.version))
        version = await asyncio.to_thread(version_ref.get)
        if not version.exists:
            raise HTTPException(status_code=404, detail="Cette version n'existe plus.")
        current = await asyncio.to_thread(reference.get)
        if not current.exists:
            raise HTTPException(status_code=404, detail="Fichier Work introuvable.")
        current_data = current.to_dict() or {}
        content = (version.to_dict() or {}).get("content", "")
        validate_content_size(content)
        update_payload = WorkFileUpdate(
            content=content,
            expected_version=int(current_data.get("version", 1)),
        )
        # Réutilise le même chemin de mise à jour pour conserver la version courante.
        return await update_file(
            file_id=file_id,
            payload=update_payload,
            request=request,
            user=user,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Impossible de restaurer une version Work.")
        raise HTTPException(status_code=503, detail="Impossible de restaurer cette version.") from exc


@router.delete("/api/work/files/{file_id}")
async def delete_file(
    file_id: str,
    request: Request,
    user: dict = Depends(require_authenticated_user),
    db: Any | None = Depends(get_db),
):
    db = _require_firestore(db)
    await _quota(request, user, db, "work_delete")
    file_id = _validate_id(file_id)
    reference = _user_collection(db, user["uid"], "work_files").document(file_id)
    try:
        snapshot = await asyncio.to_thread(reference.get)
        if not snapshot.exists:
            return {"deleted": False, "id": file_id}
        versions = await asyncio.to_thread(
            lambda: list(reference.collection("versions").stream())
        )
        for version in versions:
            await asyncio.to_thread(version.reference.delete)
        await asyncio.to_thread(reference.delete)
        return {"deleted": True, "id": file_id}
    except Exception as exc:
        logger.exception("Impossible de supprimer un fichier Work.")
        raise HTTPException(status_code=503, detail="Impossible de supprimer le fichier Work.") from exc
