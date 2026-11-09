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


class PrimeInkFicheStudentReference(BaseModel):
    """Élève connu de PrimeInk transmis comme référence de rapprochement."""
    model_config = ConfigDict(extra="forbid")

    student_id: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=240)


class PrimeInkFicheRequest(BaseModel):
    """Photo et contexte minimal nécessaires à l'extraction d'une fiche PrimeInk."""
    imageBase64: str = Field(min_length=16, max_length=8_100_000)
    class_name: str = Field(default="", max_length=160)
    course_name: str = Field(default="", max_length=160)
    max_period_points: float = Field(ge=0, le=1000)
    max_exam_points: float = Field(ge=0, le=1000)
    students: list[PrimeInkFicheStudentReference] = Field(default_factory=list, max_length=200)


class PrimeInkExtractedStudent(BaseModel):
    """Notes lues sur une ligne et association éventuelle à un élève connu."""
    model_config = ConfigDict(extra="forbid")

    matched_student_id: str | None = Field(default=None, max_length=100)
    student_name: str = Field(default="", max_length=240)
    p1: float | None = Field(default=None, ge=0, le=1000)
    p2: float | None = Field(default=None, ge=0, le=1000)
    ex1: float | None = Field(default=None, ge=0, le=1000)
    p3: float | None = Field(default=None, ge=0, le=1000)
    p4: float | None = Field(default=None, ge=0, le=1000)
    ex2: float | None = Field(default=None, ge=0, le=1000)
    confidence: float = Field(default=0, ge=0, le=1)
    warning: str | None = Field(default=None, max_length=300)


class PrimeInkFicheExtraction(BaseModel):
    """Réponse structurée de Llink destinée à l'écran de vérification PrimeInk."""
    model_config = ConfigDict(extra="forbid")

    document_type: Literal["fiche_notes", "other"] = "other"
    school_name: str | None = Field(default=None, max_length=180)
    class_name: str | None = Field(default=None, max_length=160)
    course_name: str | None = Field(default=None, max_length=160)
    academic_year: str | None = Field(default=None, max_length=80)
    students: list[PrimeInkExtractedStudent] = Field(default_factory=list, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    confidence: float = Field(default=0, ge=0, le=1)


class PrimeInkPhotoListRequest(BaseModel):
    """Image et contexte facultatif pour extraire une liste depuis un document scolaire."""
    imageBase64: str = Field(min_length=16, max_length=8_100_000)
    class_name: str = Field(default="", max_length=160)


class PrimeInkExtractedStudentIdentity(BaseModel):
    """Identité d'un élève lue sur une liste, sans inventer les champs absents."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    postname: str | None = Field(default=None, max_length=160)
    prename: str | None = Field(default=None, max_length=160)
    sexe: Literal["M", "F"] | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    warning: str | None = Field(default=None, max_length=300)


class PrimeInkStudentListExtraction(BaseModel):
    """Résultat structuré d'une photo de liste d'élèves."""
    model_config = ConfigDict(extra="forbid")

    document_type: Literal["student_list", "other"] = "other"
    class_name: str | None = Field(default=None, max_length=160)
    academic_year: str | None = Field(default=None, max_length=80)
    students: list[PrimeInkExtractedStudentIdentity] = Field(default_factory=list, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    confidence: float = Field(default=0, ge=0, le=1)


class PrimeInkExtractedCourseIdentity(BaseModel):
    """Cours lu sur un bulletin avec son domaine et son sous-domaine."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=180)
    # Maximum réellement visible pour une période ordinaire (P1/P2/P3/P4).
    # None lorsque le bulletin ne permet pas de l'identifier sans ambiguïté.
    maxPer: float | None = Field(default=None, gt=0, le=100000)
    domain: str | None = Field(default=None, max_length=180)
    subdomain: str | None = Field(default=None, max_length=180)
    confidence: float = Field(default=0, ge=0, le=1)
    warning: str | None = Field(default=None, max_length=300)


class PrimeInkCourseListExtraction(BaseModel):
    """Résultat structuré des cours d'un bulletin."""
    model_config = ConfigDict(extra="forbid")

    document_type: Literal["bulletin_courses", "other"] = "other"
    school_name: str | None = Field(default=None, max_length=180)
    class_name: str | None = Field(default=None, max_length=160)
    academic_year: str | None = Field(default=None, max_length=80)
    courses: list[PrimeInkExtractedCourseIdentity] = Field(default_factory=list, max_length=200)
    warnings: list[str] = Field(default_factory=list, max_length=100)
    confidence: float = Field(default=0, ge=0, le=1)


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
