"""Schémas Pydantic des contrats HTTP et limites d'entrée."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from llink_api.config import get_settings


class AccountDeletionRequest(BaseModel):
    """Confirmation explicite d’une suppression irréversible de compte."""
    confirmation: Literal["SUPPRIMER MON COMPTE"]


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


class ConversationTurn(BaseModel):
    """Un tour de conversation antérieur fourni par le client."""
    role: Literal["user", "assistant", "bot"]
    text: str = Field(min_length=1, max_length=32_000)


class ChatPayload(BaseModel):
    message: str = Field(min_length=1, max_length=get_settings().max_message_chars)
    # Jusqu'à 24 tours reçus ; le backend applique aussi un budget global de caractères.
    history: list[ConversationTurn] = Field(default_factory=list, max_length=24)
    model: str = Field(min_length=1, max_length=100)
    level: Optional[Literal["velora", "satori", "noetra", "auren", "omnis"]] = None
    effort: Literal["normal", "extra", "ultime"] = "normal"
    preferences: Optional[str] = Field(default=None, max_length=get_settings().max_preferences_chars)
    mode: Optional[str] = Field(default="chat", max_length=32)
    source: Optional[str] = Field(default="soko_master", max_length=100)
    source_language: Optional[str] = Field(default=None, min_length=2, max_length=16, pattern=r"^[A-Za-z0-9-]+$")
    target_language: Optional[str] = Field(default=None, min_length=2, max_length=16, pattern=r"^[A-Za-z0-9-]+$")
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
    syncId: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=200)
    time: int | float | None = None
    mode: str | None = Field(default=None, max_length=32)
    messages: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class HistorySyncResponse(BaseModel):
    status: Literal["success", "skipped"]


class HistoryResponse(BaseModel):
    chats: list[dict[str, Any]]
    warning: str | None = None


class UsageResponse(BaseModel):
    level: str
    hour_started_at: int
    reset_at: int
    request_count: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    estimated_cost_usd: float
    reserved_cost_usd: float
    hourly_budget_usd: float | None = None
    remaining_budget_usd: float | None = None


class HealthResponse(BaseModel):
    message: str
