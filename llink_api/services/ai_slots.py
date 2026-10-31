"""Limite la concurrence des appels aux fournisseurs IA par processus."""

import asyncio
import threading

from fastapi import HTTPException

from llink_api.config import get_settings

_settings = get_settings()
_semaphore = threading.BoundedSemaphore(_settings.ai_max_concurrent)


async def reserve_ai_slot() -> None:
    """Réserve un emplacement IA ; échoue rapidement si la file est saturée."""
    acquired = await asyncio.to_thread(
        _semaphore.acquire,
        True,
        _settings.ai_queue_timeout_seconds,
    )
    if not acquired:
        raise HTTPException(
            status_code=503,
            detail="Les services IA sont actuellement très sollicités. Réessayez.",
            headers={"Retry-After": "5"},
        )


def release_ai_slot() -> None:
    """Libère l'emplacement réservé à la fin de la réponse HTTP."""
    _semaphore.release()


def reset_ai_slots_for_tests() -> None:
    """Réinitialise la limite après les tests ; ne pas appeler en production."""
    global _semaphore
    _semaphore = threading.BoundedSemaphore(_settings.ai_max_concurrent)
