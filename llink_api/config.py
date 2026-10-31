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


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        parsed = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"La variable {name} doit être un entier.") from exc
    if parsed < minimum:
        raise ValueError(f"La variable {name} doit être supérieure ou égale à {minimum}.")
    return parsed


@dataclass(frozen=True)
class Settings:
    firebase_config: str | None
    gemini_api_key: str
    huggingface_token: str
    resend_api_key: str
    cors_origins: tuple[str, ...]
    enable_dataset_collection: bool
    environment: str
    max_request_body_bytes: int
    max_image_bytes: int
    max_audio_bytes: int
    max_message_chars: int
    max_preferences_chars: int
    provider_timeout_seconds: int
    ai_max_concurrent: int
    ai_queue_timeout_seconds: int


def get_settings() -> Settings:
    """Relit les variables d'environnement pour faciliter les tests et le déploiement."""
    raw_origins = os.getenv("CORS_ORIGINS")
    origins = (
        tuple(origin.strip() for origin in raw_origins.split(",") if origin.strip())
        if raw_origins is not None
        else DEFAULT_CORS_ORIGINS
    )
    if not origins:
        raise ValueError("CORS_ORIGINS ne peut pas être vide.")
    if "*" in origins:
        raise ValueError("CORS_ORIGINS ne peut pas contenir '*' lorsque les credentials sont activés.")

    default_environment = "production" if os.getenv("RENDER", "").lower() == "true" else "development"
    environment = os.getenv("APP_ENV", default_environment).strip().lower()
    if environment not in {"development", "test", "staging", "production"}:
        raise ValueError("APP_ENV doit valoir development, test, staging ou production.")

    return Settings(
        firebase_config=os.getenv("FIREBASE_CONFIG"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        huggingface_token=os.getenv("HF_TOKEN", ""),
        resend_api_key=os.getenv("RESEND_API_KEY", ""),
        cors_origins=origins,
        enable_dataset_collection=os.getenv("ENABLE_DATASET_COLLECTION", "false").lower()
        in {"1", "true", "yes"},
        environment=environment,
        max_request_body_bytes=_int_env("MAX_REQUEST_BODY_BYTES", 13_500_000),
        max_image_bytes=_int_env("MAX_IMAGE_BYTES", 6_000_000),
        max_audio_bytes=_int_env("MAX_AUDIO_BYTES", 12_000_000),
        max_message_chars=_int_env("MAX_MESSAGE_CHARS", 12_000),
        max_preferences_chars=_int_env("MAX_PREFERENCES_CHARS", 2_000),
        provider_timeout_seconds=_int_env("PROVIDER_TIMEOUT_SECONDS", 60),
        ai_max_concurrent=_int_env("AI_MAX_CONCURRENT", 4),
        ai_queue_timeout_seconds=_int_env("AI_QUEUE_TIMEOUT_SECONDS", 3),
    )
