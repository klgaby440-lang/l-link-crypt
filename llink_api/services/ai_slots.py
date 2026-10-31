"""Limite la concurrence des appels aux fournisseurs IA par processus."""

import asyncio
import threading
from collections.abc import Callable

from fastapi import HTTPException

from llink_api.config import get_settings

_settings = get_settings()
_semaphore = threading.BoundedSemaphore(_settings.ai_max_concurrent)


async def reserve_ai_slot() -> Callable[[], None]:
    """Réserve une place et retourne une libération idempotente."""
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

    release_lock = threading.Lock()
    released = False

    def release_once() -> None:
        nonlocal released
        with release_lock:
            if not released:
                _semaphore.release()
                released = True

    return release_once


def reset_ai_slots_for_tests() -> None:
    """Réinitialise la limite après les tests ; ne pas appeler en production."""
    global _semaphore
    _semaphore = threading.BoundedSemaphore(_settings.ai_max_concurrent)
