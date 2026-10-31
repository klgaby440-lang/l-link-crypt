"""Routeurs HTTP enregistrés par l'application FastAPI."""

from llink_api.api.routes import chat, health, history, media, users

__all__ = ["chat", "health", "history", "media", "users"]
