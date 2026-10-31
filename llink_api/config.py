"""Configuration centralisée du backend Llink."""

from dataclasses import dataclass
import os


DEFAULT_CORS_ORIGINS = (
    "https://ll-one-self.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://klgaby440-lang.github.io",
    "https://class-net-p.vercel.app",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
)


@dataclass(frozen=True)
class Settings:
    firebase_config: str | None
    gemini_api_key: str
    huggingface_token: str
    resend_api_key: str
    cors_origins: tuple[str, ...]
    enable_dataset_collection: bool


def get_settings() -> Settings:
    """Relit les variables d'environnement pour faciliter les tests et le déploiement."""
    raw_origins = os.getenv("CORS_ORIGINS")
    origins = (
        tuple(origin.strip() for origin in raw_origins.split(",") if origin.strip())
        if raw_origins is not None
        else DEFAULT_CORS_ORIGINS
    )
    return Settings(
        firebase_config=os.getenv("FIREBASE_CONFIG"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        huggingface_token=os.getenv("HF_TOKEN", ""),
        resend_api_key=os.getenv("RESEND_API_KEY", ""),
        cors_origins=origins,
        # Double verrou : la collecte doit être activée côté serveur ET demandée
        # explicitement dans le corps de la requête (champ data_collection_consent).
        enable_dataset_collection=os.getenv("ENABLE_DATASET_COLLECTION", "false").lower()
        in {"1", "true", "yes"},
    )
