"""Routes internes de supervision CRYPT Console.

Ces routes ne sont jamais exposées au navigateur public : elles exigent un secret
de service distinct de Think SSO et des jetons Firebase des utilisateurs.
"""
from __future__ import annotations

import os
import re
import secrets
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from firebase_admin import auth as firebase_auth
from google.api_core.exceptions import NotFound

from llink_api.database import get_db

router = APIRouter(prefix="/api/internal/crypt-console", tags=["crypt-console-internal"])
THINK_ID_RE = re.compile(r"^THK-[A-F0-9]{12}$")


def _require_console_service(token: str | None) -> None:
    expected = os.getenv("CRYPT_CONSOLE_SERVICE_TOKEN", "").strip()
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail="CRYPT_CONSOLE_SERVICE_TOKEN n'est pas configuré.")
    if not token or not secrets.compare_digest(token.strip(), expected):
        raise HTTPException(status_code=401, detail="Authentification CRYPT Console invalide.")


def _limited_collection(db: Any, name: str, limit: int = 5000) -> tuple[list[dict[str, Any]], bool]:
    query = db.collection(name).limit(limit + 1)
    rows = []
    for snapshot in query.stream():
        rows.append(snapshot.to_dict() or {})
        if len(rows) > limit:
            break
    return rows[:limit], len(rows) > limit


@router.get("/overview")
def crypt_console_overview(
    x_crypt_console_token: str | None = Header(default=None, alias="X-CRYPT-CONSOLE-TOKEN"),
):
    _require_console_service(x_crypt_console_token)
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Firestore Llink n'est pas connecté.")

    wallets, wallets_truncated = _limited_collection(db, "llink_credit_wallets")
    usages, usages_truncated = _limited_collection(db, "llink_credit_transactions", 5000)
    grants, grants_truncated = _limited_collection(db, "llink_credit_purchase_grants", 5000)

    totals = {
        "online_balance": 0,
        "offline_balance": 0,
        "daily_free_balance": 0,
        "reserved_online": 0,
        "reserved_free": 0,
        "credit_debt": 0,
    }
    for item in wallets:
        for key in totals:
            totals[key] += max(0, int(item.get(key, 0) or 0))

    usage_credits = sum(max(0, int(row.get("credits", 0) or 0)) for row in usages)
    purchased_credits = sum(max(0, int(row.get("credits", 0) or 0)) for row in grants)
    return {
        "status": True,
        "data": {
            "wallets_scanned": len(wallets),
            "wallets_truncated": wallets_truncated,
            "credit_totals": totals,
            "usage_transactions_scanned": len(usages),
            "usage_transactions_truncated": usages_truncated,
            "usage_credits_scanned": usage_credits,
            "purchase_grants_scanned": len(grants),
            "purchase_grants_truncated": grants_truncated,
            "purchased_credits_scanned": purchased_credits,
            "credit_usd_per_unit": "0.01",
            "snapshot_at_epoch": int(time.time()),
        },
    }


@router.get("/users/{think_id}/wallet")
def crypt_console_user_wallet(
    think_id: str,
    x_crypt_console_token: str | None = Header(default=None, alias="X-CRYPT-CONSOLE-TOKEN"),
):
    _require_console_service(x_crypt_console_token)
    normalized = think_id.strip().upper()
    if not THINK_ID_RE.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="Think ID invalide.")
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Firestore Llink n'est pas connecté.")

    uid = "think_" + normalized.lower()
    ref = db.collection("llink_credit_wallets").document(uid)
    snapshot = ref.get()
    wallet = snapshot.to_dict() or {}
    transactions = []
    for row in ref.collection("transactions").order_by(
        "created_at_epoch", direction="DESCENDING"
    ).limit(50).stream():
        item = row.to_dict() or {}
        item["id"] = row.id
        transactions.append(item)
    try:
        firebase_user = firebase_auth.get_user(uid)
        firebase_status = {"exists": True, "disabled": bool(firebase_user.disabled)}
    except (firebase_auth.UserNotFoundError, NotFound):
        firebase_status = {"exists": False, "disabled": None}

    public_wallet = {
        key: max(0, int(wallet.get(key, 0) or 0))
        for key in (
            "online_balance", "offline_balance", "daily_free_balance",
            "reserved_online", "reserved_free", "credit_debt",
        )
    }
    return {
        "status": True,
        "data": {
            "think_id": normalized,
            "firebase_uid": uid,
            "wallet_exists": bool(snapshot.exists),
            "wallet": public_wallet,
            "firebase": firebase_status,
            "transactions": transactions,
        },
    }


@router.patch("/users/{think_id}/status")
def crypt_console_user_status(
    think_id: str,
    payload: dict[str, Any],
    x_crypt_console_token: str | None = Header(default=None, alias="X-CRYPT-CONSOLE-TOKEN"),
):
    _require_console_service(x_crypt_console_token)
    normalized = think_id.strip().upper()
    if not THINK_ID_RE.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="Think ID invalide.")
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="enabled doit être un booléen.")
    uid = "think_" + normalized.lower()
    try:
        user = firebase_auth.update_user(uid, disabled=not enabled)
    except firebase_auth.UserNotFoundError:
        raise HTTPException(status_code=404, detail="Compte Firebase Llink introuvable pour ce Think ID.") from None
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Impossible de modifier le statut du compte Llink.") from exc
    return {
        "status": True,
        "data": {"think_id": normalized, "enabled": not bool(user.disabled)},
    }
