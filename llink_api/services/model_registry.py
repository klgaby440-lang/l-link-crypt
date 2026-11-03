"""Registre serveur des modèles et de leurs tarifs de référence."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

ModelLevel = Literal["velora", "satori", "noetra", "auren", "omnis"]


@dataclass(frozen=True)
class ModelDefinition:
    level: ModelLevel
    label: str
    provider: str
    model_id: str
    display_model: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    cached_input_usd_per_million: Decimal
    max_output_tokens: int = 2048


# Tarifs de référence vérifiés le 1er novembre 2026.
# DeepSeek est tarifé au tarif peak, plus élevé, par prudence.
MODEL_REGISTRY: dict[str, ModelDefinition] = {
    "velora": ModelDefinition(
        level="velora", label="VELORA", provider="gemini",
        model_id="gemini-3.5-flash-lite", display_model="Gemini 3.5 Flash-Lite",
        input_usd_per_million=Decimal("0.30"),
        output_usd_per_million=Decimal("2.50"),
        cached_input_usd_per_million=Decimal("0.03"),
    ),
    "satori": ModelDefinition(
        level="satori", label="SATORI", provider="zai",
        model_id="glm-4.7-flash", display_model="zai-org/GLM-4.7-Flash",
        input_usd_per_million=Decimal("0"),
        output_usd_per_million=Decimal("0"),
        cached_input_usd_per_million=Decimal("0"),
    ),
    "noetra": ModelDefinition(
        level="noetra", label="NOETRA", provider="minimax",
        model_id="MiniMax-M3.1-Flash", display_model="MiniMaxAI/MiniMax-M3.1-Flash",
        input_usd_per_million=Decimal("0.15"),
        output_usd_per_million=Decimal("0.60"),
        cached_input_usd_per_million=Decimal("0.015"),
    ),
    "auren": ModelDefinition(
        level="auren", label="AUREN", provider="deepseek",
        model_id="deepseek-flash", display_model="DeepSeek-V4.1-Flash-1017",
        input_usd_per_million=Decimal("0.30"),
        output_usd_per_million=Decimal("1.20"),
        cached_input_usd_per_million=Decimal("0.006"),
    ),
    "omnis": ModelDefinition(
        level="omnis", label="OMNIS", provider="zai",
        model_id="glm-5", display_model="zai-org/GLM-5",
        input_usd_per_million=Decimal("1.00"),
        output_usd_per_million=Decimal("3.20"),
        cached_input_usd_per_million=Decimal("0.20"),
    ),
}

LEVEL_ORDER = ("velora", "satori", "noetra", "auren", "omnis")
PLAN_TO_LEVEL = {
    "bronze": "satori",
    "silver": "noetra",
    "gold": "auren",
    "diamant": "omnis",
}

# Compatibilité avec les anciennes valeurs envoyées par le frontend.
# Le fournisseur et l'identifiant réels viennent toujours du registre serveur.
LEGACY_MODEL_ALIASES = {
    "gemini-1.5-flash": "velora",
    "gemini-2.5-flash": "velora",
    "gemini-3.5-flash-lite": "velora",
    "deepseek-v3": "satori",
    "llama-3-8b": "satori",
    "mistral-7b": "satori",
}


def resolve_model(level: str | None, legacy_model: str | None = None) -> ModelDefinition:
    """Résout un niveau explicite ou un alias historique sans faire confiance au modèle client."""
    requested = (level or "").strip().lower()
    if not requested:
        requested = LEGACY_MODEL_ALIASES.get((legacy_model or "").strip().lower(), "")
    if requested not in MODEL_REGISTRY:
        raise ValueError("Niveau IA inconnu. Choisissez un niveau Llink valide.")
    return MODEL_REGISTRY[requested]


def user_can_access_level(entitled_level: str, requested_level: str) -> bool:
    """Compare les droits par niveau, dans l'ordre VELORA à OMNIS."""
    try:
        return LEVEL_ORDER.index(requested_level) <= LEVEL_ORDER.index(entitled_level)
    except ValueError:
        return False
