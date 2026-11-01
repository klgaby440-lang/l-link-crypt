"""Adaptateur Gemini fondé sur le SDK officiel google-genai."""

from collections.abc import Iterator
from typing import Any

from google import genai
from google.genai import types

from llink_api.config import get_settings


MODEL_NAME = "gemini-3.5-flash-lite"
EFFORT_TO_THINKING_LEVEL = {
    "normal": "minimal",
    "extra": "medium",
    "ultime": "high",
}


def build_gemini_contents(
    conversation_history: list[dict[str, str]],
    user_text: str,
) -> list[types.Content]:
    """Convertit l'historique de Llink en tours Gemini user/model."""
    contents: list[types.Content] = []
    for item in conversation_history:
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        contents.append(
            types.Content(
                role="model" if role == "assistant" else "user",
                parts=[types.Part.from_text(text=content)],
            )
        )
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_text)],
        )
    )
    return contents


class GeminiModelAdapter:
    """Expose l'ancienne interface interne tout en utilisant le SDK google-genai."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        system_instruction: str | None,
        effort: str,
        timeout_seconds: int,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.system_instruction = system_instruction
        self.effort = effort if effort in EFFORT_TO_THINKING_LEVEL else "normal"
        self.timeout_ms = max(1, int(timeout_seconds * 1000))

    def _config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=self.system_instruction,
            max_output_tokens=2048,
            thinking_config=types.ThinkingConfig(
                thinking_level=EFFORT_TO_THINKING_LEVEL[self.effort]
            ),
        )

    def _client(self):
        return genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=self.timeout_ms),
        )


    @staticmethod
    def _normalize_contents(contents: Any) -> Any:
        """Convertit les parts multimédias au format de l'ancien adaptateur interne."""
        if not isinstance(contents, list):
            return contents
        normalized = []
        for item in contents:
            if isinstance(item, dict) and "mime_type" in item and "data" in item:
                normalized.append(
                    types.Part.from_bytes(
                        data=item["data"],
                        mime_type=item["mime_type"],
                    )
                )
            else:
                normalized.append(item)
        return normalized

    def generate_content(
        self,
        contents: Any,
        *,
        stream: bool = False,
        request_options: dict[str, Any] | None = None,
    ):
        """Génère une réponse normale ou retourne un itérateur synchrone de fragments."""
        # Le timeout est configuré sur HttpOptions du client google-genai.
        del request_options
        contents = self._normalize_contents(contents)
        if stream:
            def generate_stream() -> Iterator[Any]:
                with self._client() as client:
                    yield from client.models.generate_content_stream(
                        model=self.model_name,
                        contents=contents,
                        config=self._config(),
                    )

            return generate_stream()

        with self._client() as client:
            return client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=self._config(),
            )


def get_gemini_model(
    system_instruction: str | None = None,
    model_name: str = MODEL_NAME,
    effort: str = "normal",
) -> GeminiModelAdapter:
    """Retourne l'adaptateur Gemini ou signale une configuration absente."""
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("Clé API Gemini manquante sur le serveur.")
    return GeminiModelAdapter(
        api_key=settings.gemini_api_key,
        model_name=model_name,
        system_instruction=system_instruction,
        effort=effort,
        timeout_seconds=settings.provider_timeout_seconds,
    )
