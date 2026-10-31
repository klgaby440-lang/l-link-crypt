"""Entrée ASGI conservant la commande de démarrage historique : uvicorn main:app."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from llink_api.api.routes import chat, health, history, media, users
from llink_api.config import get_settings


def create_app() -> FastAPI:
    """Construit l'application FastAPI et enregistre les routes."""
    settings = get_settings()
    application = FastAPI(
        title="Llink API Server - CRYPT ENGINE",
        version="1.0.0",
        description="API de Llink, le produit IA de CRYPT.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(health.router)
    application.include_router(users.router)
    application.include_router(chat.router)
    application.include_router(media.router)
    application.include_router(history.router)
    return application


# Compatibilité Render / Uvicorn : la cible reste main:app.
app = create_app()
