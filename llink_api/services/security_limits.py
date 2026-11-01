"""Quotas par fonction : transaction Firestore en production, mémoire en local."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from google.cloud import firestore as google_firestore

from llink_api.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuotaPolicy:
    per_minute: int
    per_day: int


DEFAULT_POLICIES: dict[tuple[str, bool], QuotaPolicy] = {
    ("chat", False): QuotaPolicy(3, 20),
    ("chat", True): QuotaPolicy(12, 240),
    ("ocr", False): QuotaPolicy(1, 5),
    ("ocr", True): QuotaPolicy(5, 40),
    ("audio", False): QuotaPolicy(1, 3),
    ("audio", True): QuotaPolicy(3, 20),
    ("attachment", False): QuotaPolicy(2, 10),
    ("attachment", True): QuotaPolicy(5, 30),
    ("history_read", True): QuotaPolicy(30, 200),
    ("history_sync", True): QuotaPolicy(30, 500),
    ("history_delete", True): QuotaPolicy(20, 100),
    ("data_export", True): QuotaPolicy(2, 10),
    ("account_delete", True): QuotaPolicy(1, 2),
    ("user_status", False): QuotaPolicy(3, 20),
    ("user_status", True): QuotaPolicy(30, 300),
    ("payment_verify", True): QuotaPolicy(3, 10),
    ("usage_read", True): QuotaPolicy(30, 200),
}

_memory_lock = threading.Lock()
_memory_windows: dict[str, dict[str, int]] = {}


def _env_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} doit être un entier positif.") from exc
    if value < 1:
        raise RuntimeError(f"{name} doit être supérieur ou égal à 1.")
    return value


def get_quota_policy(scope: str, authenticated: bool) -> QuotaPolicy:
    """Retourne la politique par défaut, surchargeable par variables d'environnement."""
    key = (scope, authenticated)
    policy = DEFAULT_POLICIES.get(key)
    if policy is None:
        raise RuntimeError(f"Aucune politique de quota définie pour {scope}.")
    audience = "USER" if authenticated else "ANON"
    prefix = f"QUOTA_{audience}_{scope.upper()}"
    return QuotaPolicy(
        per_minute=_env_positive_int(f"{prefix}_PER_MINUTE", policy.per_minute),
        per_day=_env_positive_int(f"{prefix}_PER_DAY", policy.per_day),
    )


def _quota_document_id(principal: str, scope: str) -> str:
    return hashlib.sha256(f"{scope}:{principal}".encode("utf-8")).hexdigest()


def delete_user_rate_limit_records(db: Any, uid: str) -> int:
    """Supprime les compteurs pseudonymisés connus de ce compte."""
    collection = db.collection("api_rate_limits")
    deleted = 0
    principal = f"uid:{uid}"
    for (scope, authenticated), _policy in DEFAULT_POLICIES.items():
        if not authenticated:
            continue
        reference = collection.document(_quota_document_id(principal, scope))
        snapshot = reference.get()
        if snapshot.exists:
            reference.delete()
            deleted += 1
    return deleted


def _consume_firestore(
    db: Any,
    principal: str,
    scope: str,
    policy: QuotaPolicy,
) -> tuple[bool, int]:
    """Incrémente minute et jour dans une transaction Firestore atomique."""
    now = int(time.time())
    minute_bucket = now // 60
    day_bucket = now // 86_400
    reference = db.collection("api_rate_limits").document(
        _quota_document_id(principal, scope)
    )

    @google_firestore.transactional
    def update_counts(transaction):
        snapshot = reference.get(transaction=transaction)
        current = snapshot.to_dict() or {}

        minute_count = (
            int(current.get("minute_count", 0))
            if current.get("minute_bucket") == minute_bucket
            else 0
        )
        day_count = (
            int(current.get("day_count", 0))
            if current.get("day_bucket") == day_bucket
            else 0
        )

        retry_after = 0
        if minute_count >= policy.per_minute:
            retry_after = max(retry_after, 60 - (now % 60))
        if day_count >= policy.per_day:
            retry_after = max(retry_after, 86_400 - (now % 86_400))
        if retry_after:
            return False, max(1, retry_after)

        transaction.set(
            reference,
            {
                "minute_bucket": minute_bucket,
                "minute_count": minute_count + 1,
                "day_bucket": day_bucket,
                "day_count": day_count + 1,
                "updated_at_epoch": now,
            },
        )
        return True, 0

    return update_counts(db.transaction())


def _consume_memory(principal: str, scope: str, policy: QuotaPolicy) -> tuple[bool, int]:
    """Limiteur mono-processus utilisé uniquement en développement et tests."""
    now = int(time.time())
    minute_bucket = now // 60
    day_bucket = now // 86_400
    key = _quota_document_id(principal, scope)

    with _memory_lock:
        current = _memory_windows.get(key, {})
        minute_count = current.get("minute_count", 0) if current.get("minute_bucket") == minute_bucket else 0
        day_count = current.get("day_count", 0) if current.get("day_bucket") == day_bucket else 0

        retry_after = 0
        if minute_count >= policy.per_minute:
            retry_after = max(retry_after, 60 - (now % 60))
        if day_count >= policy.per_day:
            retry_after = max(retry_after, 86_400 - (now % 86_400))
        if retry_after:
            return False, max(1, retry_after)

        _memory_windows[key] = {
            "minute_bucket": minute_bucket,
            "minute_count": minute_count + 1,
            "day_bucket": day_bucket,
            "day_count": day_count + 1,
        }
        if len(_memory_windows) > 20_000:
            _memory_windows.clear()
        return True, 0


async def enforce_endpoint_quota(
    *,
    request: Request,
    user: dict,
    db: Any | None,
    scope: str,
) -> None:
    """Applique un quota durable et refuse de servir si le compteur cloud tombe."""
    authenticated = user.get("uid") != "anonymous"
    policy = get_quota_policy(scope, authenticated)
    if authenticated:
        principal = f"uid:{user['uid']}"
    else:
        client_host = request.client.host if request.client else "unknown"
        principal = f"ip:{client_host or 'unknown'}"

    settings = get_settings()
    try:
        if db is not None:
            allowed, retry_after = await asyncio.to_thread(
                _consume_firestore, db, principal, scope, policy
            )
        elif settings.environment in {"development", "test"}:
            allowed, retry_after = _consume_memory(principal, scope, policy)
        else:
            logger.error(
                "Firestore indisponible : quota cloud non vérifiable en mode %s pour %s.",
                settings.environment,
                scope,
            )
            raise HTTPException(
                status_code=503,
                detail="Service de protection des quotas indisponible. Réessayez.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Impossible de consommer le quota Firestore pour %s.", scope)
        raise HTTPException(
            status_code=503,
            detail="Service de protection des quotas indisponible. Réessayez.",
        ) from exc

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Limite temporaire atteinte pour cette fonction. Réessayez après le délai indiqué.",
            headers={"Retry-After": str(retry_after)},
        )


def reset_memory_quotas_for_tests() -> None:
    """Vide uniquement le limiteur local de développement/tests."""
    with _memory_lock:
        _memory_windows.clear()
