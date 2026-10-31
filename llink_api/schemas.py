"""Schémas Pydantic des contrats HTTP."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class VerifyPaymentRequest(BaseModel):
    transactionId: str


class PaymentVerifyResponse(BaseModel):
    success: bool


class OCRRequest(BaseModel):
    imageBase64: str


class OCRResponse(BaseModel):
    response: str


class AudioResponse(BaseModel):
    text: str


class ChatPayload(BaseModel):
    message: str
    model: str
    preferences: Optional[str] = None
    mode: Optional[str] = "chat"
    source: Optional[str] = "soko_master"
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
    title: str | None = None
    time: int | float | None = None
    mode: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)


class HistorySyncResponse(BaseModel):
    status: Literal["success", "skipped"]


class HistoryResponse(BaseModel):
    chats: list[dict[str, Any]]
    warning: str | None = None


class HealthResponse(BaseModel):
    message: str
