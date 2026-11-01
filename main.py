"""Entrée ASGI de Llink : la commande de démarrage reste uvicorn main:app."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from llink_api.api.routes import chat, data, health, history, media, usage, users
from llink_api.config import get_settings
from llink_api.middleware import RequestBodyLimitMiddleware


def create_app() -> FastAPI:
    """Construit l'application, ses routes et les protections HTTP communes."""
    settings = get_settings()
    application = FastAPI(
        title="Llink API Server - CRYPT ENGINE",
        version="1.2.0",
        description="API de Llink, le produit IA de CRYPT.",
    )
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=settings.max_request_body_bytes,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Retry-After"],
    )

    application.include_router(health.router)
    application.include_router(users.router)
    application.include_router(chat.router)
    application.include_router(media.router)
    application.include_router(history.router)
    application.include_router(data.router)
    application.include_router(usage.router)
    return application


# Compatibilité Render / Uvicorn : la cible reste main:app.
app = create_app()
