"""Registre de consommation et plafonds horaires optionnels par niveau."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from google.cloud import firestore as google_firestore

from llink_api.config import get_settings
from llink_api.providers.openai_compatible import TokenUsage
from llink_api.services.model_registry import ModelDefinition

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UsageReservation:
    request_id: str
    hour_bucket: int
    reserved_cost_microusd: int


def _ceil_microusd(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def calculate_cost_microusd(model: ModelDefinition, usage: TokenUsage) -> int:
    """Coût fournisseur estimé en micro-dollars US, arrondi vers le haut."""
    if usage.cost_microusd is not None:
        return max(0, int(usage.cost_microusd))
    cached = min(usage.prompt_tokens, usage.cached_input_tokens)
    uncached = max(0, usage.prompt_tokens - cached)
    cost = (
        Decimal(uncached) * model.input_usd_per_million
        + Decimal(cached) * model.cached_input_usd_per_million
        + Decimal(usage.completion_tokens) * model.output_usd_per_million
    )
    return _ceil_microusd(cost)


def estimate_request_cost_microusd(
    model: ModelDefinition,
    prompt: str,
    max_output_tokens: int | None = None,
) -> int:
    """Réserve prudemment une estimation avant l'appel fournisseur."""
    estimated_input_tokens = math.ceil(len(prompt) / 2) + 256
    output_tokens = max_output_tokens or model.max_output_tokens
    estimated = (
        Decimal(estimated_input_tokens) * model.input_usd_per_million
        + Decimal(output_tokens) * model.output_usd_per_million
    )
    return _ceil_microusd(estimated)


def hourly_budget_microusd(level: str) -> int | None:
    limit_usd = get_settings().hourly_credit_limits_usd.get(level)
    if limit_usd is None:
        return None
    return _ceil_microusd(Decimal(str(limit_usd)) * Decimal(1_000_000))


def _usage_refs(db: Any, uid: str, hour_bucket: int, request_id: str):
    if uid == "anonymous":
        hour_ref = db.collection("system_usage_hours").document(str(hour_bucket))
        event_ref = hour_ref.collection("usage_events").document(request_id)
        return hour_ref, event_ref

    user_ref = db.collection("users").document(uid)
    hour_ref = user_ref.collection("usage_hours").document(str(hour_bucket))
    event_ref = user_ref.collection("usage_events").document(request_id)
    return hour_ref, event_ref


async def reserve_usage_budget(
    *,
    db: Any | None,
    uid: str,
    level: str,
    model: ModelDefinition,
    prompt: str,
) -> UsageReservation | None:
    """Réserve une estimation dans une transaction avant de lancer le modèle."""
    if db is None:
        if uid != "anonymous":
            raise HTTPException(
                status_code=503,
                detail="Le registre de consommation est indisponible. Réessayez.",
            )
        return None

    now = int(time.time())
    hour_bucket = now // 3600
    estimate = estimate_request_cost_microusd(model, prompt)
    budget = hourly_budget_microusd(level)
    request_id = uuid4().hex
    hour_ref, _ = _usage_refs(db, uid, hour_bucket, request_id)

    @google_firestore.transactional
    def reserve(transaction):
        snapshot = hour_ref.get(transaction=transaction)
        current = snapshot.to_dict() or {}
        actual = int(current.get("actual_cost_microusd", 0))
        reserved = int(current.get("reserved_cost_microusd", 0))
        if budget is not None and actual + reserved + estimate > budget:
            return False
        transaction.set(
            hour_ref,
            {
                "hour_bucket": hour_bucket,
                "reserved_cost_microusd": reserved + estimate,
                "updated_at_epoch": now,
            },
            merge=True,
        )
        return True

    try:
        allowed = await asyncio.to_thread(lambda: reserve(db.transaction()))
    except Exception as exc:
        logger.exception("Impossible de réserver le budget horaire.")
        raise HTTPException(
            status_code=503,
            detail="Le registre de consommation est temporairement indisponible.",
        ) from exc

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Votre budget horaire de crédits est épuisé. Il sera renouvelé à l'heure suivante.",
            headers={"Retry-After": str(max(1, 3600 - (now % 3600)))},
        )
    return UsageReservation(
        request_id=request_id,
        hour_bucket=hour_bucket,
        reserved_cost_microusd=estimate,
    )


async def finalize_usage(
    *,
    db: Any | None,
    uid: str,
    reservation: UsageReservation | None,
    level: str,
    model: ModelDefinition,
    usage: TokenUsage | None,
    status: str,
) -> None:
    """Libère la réservation et écrit un événement sans contenu utilisateur."""
    if reservation is None or db is None:
        return

    now = int(time.time())
    hour_ref, event_ref = _usage_refs(
        db, uid, reservation.hour_bucket, reservation.request_id
    )
    has_usage = usage is not None
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    cached_tokens = usage.cached_input_tokens if usage else 0
    # Si le fournisseur n'a pas livré ses métriques, on comptabilise la réserve
    # entière pour ne pas sous-estimer la dépense.
    actual_cost = (
        calculate_cost_microusd(model, usage)
        if usage is not None
        else reservation.reserved_cost_microusd
    )

    @google_firestore.transactional
    def settle(transaction):
        event_snapshot = event_ref.get(transaction=transaction)
        if event_snapshot.exists:
            return
        hour_snapshot = hour_ref.get(transaction=transaction)
        current = hour_snapshot.to_dict() or {}
        reserved = int(current.get("reserved_cost_microusd", 0))
        transaction.set(
            hour_ref,
            {
                "hour_bucket": reservation.hour_bucket,
                "reserved_cost_microusd": max(
                    0, reserved - reservation.reserved_cost_microusd
                ),
                "actual_cost_microusd": (
                    int(current.get("actual_cost_microusd", 0)) + actual_cost
                ),
                "request_count": int(current.get("request_count", 0)) + 1,
                "input_tokens": int(current.get("input_tokens", 0)) + prompt_tokens,
                "output_tokens": int(current.get("output_tokens", 0)) + completion_tokens,
                "cached_input_tokens": (
                    int(current.get("cached_input_tokens", 0)) + cached_tokens
                ),
                "updated_at_epoch": now,
            },
            merge=True,
        )
        transaction.set(
            event_ref,
            {
                "request_id": reservation.request_id,
                "hour_bucket": reservation.hour_bucket,
                "level": level,
                "provider": model.provider,
                "model": model.model_id,
                "display_model": model.display_model,
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "cached_input_tokens": cached_tokens,
                "cost_microusd": actual_cost,
                "usage_reported_by_provider": has_usage,
                "status": status,
                "created_at_epoch": now,
            },
        )

    try:
        await asyncio.to_thread(lambda: settle(db.transaction()))
    except Exception:
        # Le résultat IA ne doit pas être remplacé par une erreur de comptabilisation.
        logger.exception("Échec de la finalisation de consommation %s.", reservation.request_id)


async def read_current_usage(*, db: Any, uid: str, level: str) -> dict[str, Any]:
    now = int(time.time())
    hour_bucket = now // 3600
    user_ref = db.collection("users").document(uid)
    hour_ref = user_ref.collection("usage_hours").document(str(hour_bucket))
    try:
        snapshot = await asyncio.to_thread(hour_ref.get)
        current = snapshot.to_dict() or {}
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Impossible de récupérer votre consommation pour le moment.",
        ) from exc

    budget = hourly_budget_microusd(level)
    actual = int(current.get("actual_cost_microusd", 0))
    reserved = int(current.get("reserved_cost_microusd", 0))
    return {
        "level": level,
        "hour_started_at": hour_bucket * 3600,
        "reset_at": (hour_bucket + 1) * 3600,
        "request_count": int(current.get("request_count", 0)),
        "input_tokens": int(current.get("input_tokens", 0)),
        "output_tokens": int(current.get("output_tokens", 0)),
        "cached_input_tokens": int(current.get("cached_input_tokens", 0)),
        "estimated_cost_usd": actual / 1_000_000,
        "reserved_cost_usd": reserved / 1_000_000,
        "hourly_budget_usd": budget / 1_000_000 if budget is not None else None,
        "remaining_budget_usd": (
            max(0, budget - actual - reserved) / 1_000_000
            if budget is not None
            else None
        ),
    }
