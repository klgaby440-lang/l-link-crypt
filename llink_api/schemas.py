"""Schémas Pydantic des contrats HTTP et limites d'entrée."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from llink_api.config import get_settings


class VerifyPaymentRequest(BaseModel):
    transactionId: str = Field(min_length=1, max_length=180)


class PaymentVerifyResponse(BaseModel):
    success: bool


class OCRRequest(BaseModel):
    imageBase64: str = Field(min_length=16, max_length=8_100_000)


class OCRResponse(BaseModel):
    response: str


class AudioResponse(BaseModel):
    text: str


class ChatPayload(BaseModel):
    message: str = Field(min_length=1, max_length=get_settings().max_message_chars)
    model: str = Field(min_length=1, max_length=100)
    preferences: Optional[str] = Field(default=None, max_length=get_settings().max_preferences_chars)
    mode: Optional[str] = Field(default="chat", max_length=32)
    source: Optional[str] = Field(default="soko_master", max_length=100)
    # Aucun entraînement/jeu de données sans demande explicite.
    data_collection_consent: bool = False


class UserStatusResponse(BaseModel):
    isValid: bool
    isTrial: bool | None = None
    expirationDate: float | None = None
    isNewUser: bool


class ChatSyncPayload(BaseModel):
    """Structure connue de Dexie ; les champs additionnels restent acceptés."""
    model_config = ConfigDict(extra="allow")

    id: int | str | None = None
    title: str | None = Field(default=None, max_length=200)
    time: int | float | None = None
    mode: str | None = Field(default=None, max_length=32)
    messages: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class HistorySyncResponse(BaseModel):
    status: Literal["success", "skipped"]


class HistoryResponse(BaseModel):
    chats: list[dict[str, Any]]
    warning: str | None = None


class HealthResponse(BaseModel):
    message: str
