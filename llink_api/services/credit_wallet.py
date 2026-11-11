"""Portefeuille de crédits Llink : solde, recharge quotidienne, réservations et journal."""

from __future__ import annotations

import asyncio
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from google.cloud import firestore as google_firestore


MICROUSD_PER_CREDIT = 10_000


@dataclass(frozen=True)
class CreditReservation:
    request_id: str
    reserved_free: int
    reserved_online: int
    reservation_date: str


def credits_for_microusd(cost_microusd: int, *, minimum_one: bool = True) -> int:
    value = max(0, int(cost_microusd))
    credits = math.ceil(value / MICROUSD_PER_CREDIT)
    return max(1, credits) if minimum_one else credits


def daily_free_credit_amount() -> int:
    try:
        amount = int(os.getenv("LLINK_DAILY_FREE_CREDITS", "5"))
    except ValueError:
        raise HTTPException(status_code=503, detail="LLINK_DAILY_FREE_CREDITS doit être un entier.") from None
    if not 0 <= amount <= 1000:
        raise HTTPException(status_code=503, detail="LLINK_DAILY_FREE_CREDITS doit être compris entre 0 et 1 000.")
    return amount


def _date_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _wallet_ref(db: Any, uid: str):
    return db.collection("llink_credit_wallets").document(uid)


def _refill_daily_free(transaction: Any, ref: Any, current: dict[str, Any], today: str) -> dict[str, Any]:
    if current.get("daily_free_date") != today:
        current["daily_free_balance"] = daily_free_credit_amount()
        current["daily_free_date"] = today
        current["daily_free_refreshed_at"] = int(time.time())
        transaction.set(ref, current, merge=True)
    return current


async def read_credit_wallet(*, db: Any, uid: str) -> dict[str, Any]:
    if not uid or uid == "anonymous":
        raise HTTPException(status_code=401, detail="Connecte-toi pour consulter ton portefeuille Llink.")
    ref = _wallet_ref(db, uid)
    today = _date_key()

    @google_firestore.transactional
    def refresh(transaction):
        snapshot = ref.get(transaction=transaction)
        current = snapshot.to_dict() or {}
        _refill_daily_free(transaction, ref, current, today)
        current.setdefault("online_balance", 0)
        current.setdefault("offline_balance", 0)
        current.setdefault("reserved_online", 0)
        current.setdefault("reserved_free", 0)
        current.setdefault("credit_debt", 0)
        transaction.set(ref, current, merge=True)
        return current

    try:
        current = await asyncio.to_thread(lambda: refresh(db.transaction()))
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=503, detail="Le portefeuille de crédits est temporairement indisponible.") from exc
    return {
        "credit_usd": "0.01",
        "online_balance": max(0, int(current.get("online_balance", 0))),
        "offline_balance": max(0, int(current.get("offline_balance", 0))),
        "daily_free_balance": max(0, int(current.get("daily_free_balance", 0))),
        "reserved_online": max(0, int(current.get("reserved_online", 0))),
        "reserved_free": max(0, int(current.get("reserved_free", 0))),
        "credit_debt": max(0, int(current.get("credit_debt", 0))),
        "daily_free_date": current.get("daily_free_date", today),
        "offline_spending_enabled": False,
        "offline_note": "Le portefeuille Offline est réservé aux crédits préautorisés par un appareil ; les dépenses hors connexion ne sont pas encore activées.",
    }


async def grant_verified_purchase(
    *, db: Any, uid: str, public_id: str, credits: int, wallet_type: str = "online",
) -> dict[str, Any]:
    if not uid or uid == "anonymous" or not public_id or credits < 1:
        raise HTTPException(status_code=422, detail="Achat de crédits invalide.")
    if wallet_type not in {"online", "offline"}:
        raise HTTPException(status_code=422, detail="Type de portefeuille inconnu.")
    if wallet_type == "offline":
        raise HTTPException(status_code=409, detail="Les achats Offline resteront désactivés jusqu'à la mise en place des autorisations signées par appareil.")
    wallet_ref = _wallet_ref(db, uid)
    grant_ref = db.collection("llink_credit_purchase_grants").document(public_id)
    now = int(time.time())

    @google_firestore.transactional
    def grant(transaction):
        existing = grant_ref.get(transaction=transaction)
        if existing.exists:
            data = existing.to_dict() or {}
            if data.get("uid") != uid or int(data.get("credits", 0)) != credits:
                raise HTTPException(status_code=409, detail="Cette référence de paiement est déjà liée à un autre achat.")
            return {"granted": False, "balance": None}
        wallet_snapshot = wallet_ref.get(transaction=transaction)
        wallet = wallet_snapshot.to_dict() or {}
        debt = max(0, int(wallet.get("credit_debt", 0)))
        applied = max(0, credits - debt)
        wallet["credit_debt"] = max(0, debt - credits)
        wallet["online_balance"] = max(0, int(wallet.get("online_balance", 0))) + applied
        wallet["updated_at_epoch"] = now
        transaction.set(wallet_ref, wallet, merge=True)
        transaction.create(grant_ref, {
            "uid": uid, "public_id": public_id, "credits": credits,
            "wallet_type": wallet_type, "applied_credits": applied,
            "debt_repaid": min(credits, debt), "created_at_epoch": now,
        })
        ledger_ref = wallet_ref.collection("transactions").document(public_id)
        transaction.create(ledger_ref, {
            "type": "purchase", "credits": credits, "applied_credits": applied,
            "wallet_type": wallet_type, "reference": public_id,
            "created_at_epoch": now,
        })
        return {"granted": True, "balance": wallet["online_balance"], "applied_credits": applied}

    try:
        return await asyncio.to_thread(lambda: grant(db.transaction()))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Impossible d'enregistrer l'achat dans le portefeuille Llink.") from exc


async def reserve_credit_usage(
    *, db: Any, uid: str, estimated_cost_microusd: int, allow_daily_free: bool,
) -> CreditReservation:
    if not uid or uid == "anonymous":
        raise HTTPException(status_code=401, detail="Un compte connecté est requis pour utiliser les crédits Llink.")
    amount = credits_for_microusd(estimated_cost_microusd)
    today = _date_key()
    request_id = uuid4().hex
    wallet_ref = _wallet_ref(db, uid)
    reservation_ref = db.collection("llink_credit_reservations").document(request_id)

    @google_firestore.transactional
    def reserve(transaction):
        snapshot = wallet_ref.get(transaction=transaction)
        wallet = snapshot.to_dict() or {}
        _refill_daily_free(transaction, wallet_ref, wallet, today)
        debt = max(0, int(wallet.get("credit_debt", 0)))
        if debt:
            raise HTTPException(status_code=402, detail="Ton portefeuille présente une consommation à régulariser. Recharge des crédits pour continuer.")
        free_balance = max(0, int(wallet.get("daily_free_balance", 0)))
        online_balance = max(0, int(wallet.get("online_balance", 0)))
        free = min(amount, free_balance) if allow_daily_free else 0
        paid = amount - free
        if online_balance < paid:
            needed = paid - online_balance
            raise HTTPException(
                status_code=402,
                detail=f"Crédits insuffisants. Il manque {needed} crédit(s) Online. Recharge ton portefeuille pour continuer.",
            )
        wallet["daily_free_balance"] = free_balance - free
        wallet["online_balance"] = online_balance - paid
        wallet["reserved_free"] = max(0, int(wallet.get("reserved_free", 0))) + free
        wallet["reserved_online"] = max(0, int(wallet.get("reserved_online", 0))) + paid
        wallet["updated_at_epoch"] = int(time.time())
        transaction.set(wallet_ref, wallet, merge=True)
        transaction.create(reservation_ref, {
            "uid": uid, "request_id": request_id, "reserved_free": free,
            "reserved_online": paid, "reservation_date": today,
            "status": "reserved", "created_at_epoch": int(time.time()),
        })
        return free, paid

    try:
        free, paid = await asyncio.to_thread(lambda: reserve(db.transaction()))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Impossible de réserver les crédits avant le traitement.") from exc
    return CreditReservation(request_id, free, paid, today)


async def settle_credit_usage(
    *, db: Any, uid: str, reservation: CreditReservation | None,
    actual_cost_microusd: int, status: str, level: str, model: str,
    input_tokens: int = 0, output_tokens: int = 0,
) -> None:
    if reservation is None or db is None:
        return
    wallet_ref = _wallet_ref(db, uid)
    reservation_ref = db.collection("llink_credit_reservations").document(reservation.request_id)
    event_ref = db.collection("llink_credit_transactions").document(reservation.request_id)
    actual = credits_for_microusd(actual_cost_microusd)
    now = int(time.time())

    @google_firestore.transactional
    def settle(transaction):
        row_snapshot = reservation_ref.get(transaction=transaction)
        if not row_snapshot.exists:
            return
        row = row_snapshot.to_dict() or {}
        if row.get("status") == "settled":
            return
        wallet_snapshot = wallet_ref.get(transaction=transaction)
        wallet = wallet_snapshot.to_dict() or {}
        reserved_free = max(0, int(row.get("reserved_free", 0)))
        reserved_online = max(0, int(row.get("reserved_online", 0)))
        reserved_total = reserved_free + reserved_online
        charge_free = min(actual, reserved_free)
        charge_online_reserved = min(max(0, actual - charge_free), reserved_online)
        extra = max(0, actual - reserved_total)
        online_balance = max(0, int(wallet.get("online_balance", 0)))
        extra_paid = min(extra, online_balance)
        debt_added = extra - extra_paid
        unused_free = reserved_free - charge_free
        unused_online = reserved_online - charge_online_reserved
        wallet["reserved_free"] = max(0, int(wallet.get("reserved_free", 0)) - reserved_free)
        wallet["reserved_online"] = max(0, int(wallet.get("reserved_online", 0)) - reserved_online)
        wallet["online_balance"] = online_balance - extra_paid + unused_online
        if row.get("reservation_date") == _date_key():
            wallet["daily_free_balance"] = max(0, int(wallet.get("daily_free_balance", 0))) + unused_free
        wallet["credit_debt"] = max(0, int(wallet.get("credit_debt", 0))) + debt_added
        wallet["updated_at_epoch"] = now
        transaction.set(wallet_ref, wallet, merge=True)
        row.update({"status": "settled", "actual_credits": actual,
                    "charged_free": charge_free, "charged_online": charge_online_reserved + extra_paid,
                    "debt_added": debt_added, "settled_at_epoch": now})
        transaction.set(reservation_ref, row, merge=True)
        transaction.create(event_ref, {
            "type": "usage", "request_id": reservation.request_id, "uid": uid,
            "credits": actual, "cost_microusd": max(0, int(actual_cost_microusd)),
            "level": level, "model": model, "status": status,
            "input_tokens": int(input_tokens), "output_tokens": int(output_tokens),
            "created_at_epoch": now,
        })

    try:
        await asyncio.to_thread(lambda: settle(db.transaction()))
    except Exception:
        # Ne jamais remplacer une réponse IA par une erreur du registre financier.
        import logging
        logging.getLogger(__name__).exception("Échec de règlement du portefeuille Llink (%s).", reservation.request_id)
