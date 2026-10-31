"""Adaptateur de streaming Hugging Face Inference Router."""

import json
import logging
from collections.abc import AsyncIterator

import httpx

from llink_api.config import get_settings

logger = logging.getLogger(__name__)
CHAT_COMPLETIONS_URL = "https://router.huggingface.co/v1/chat/completions"


def resolve_huggingface_model(selected_model: str) -> str:
    """Conserve le mapping historique ; le registre unifié sera traité en phase 3."""
    selected = selected_model.lower()
    if "deepseek" in selected:
        return "deepseek-ai/DeepSeek-V3"
    if "llama" in selected:
        return "meta-llama/Meta-Llama-3-8B-Instruct"
    return "mistralai/Mistral-7B-Instruct-v0.3"


async def stream_huggingface(
    *,
    model_id: str,
    system_instruction: str,
    user_text: str,
) -> AsyncIterator[str]:
    """Émet les fragments de texte d'une réponse OpenAI-compatible."""
    token = get_settings().huggingface_token
    if not token:
        raise RuntimeError("Token HF manquant.")

    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.7,
        "max_tokens": 2048,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    timeout = get_settings().provider_timeout_seconds
    http_timeout = httpx.Timeout(timeout, connect=min(10.0, timeout), write=15.0, pool=5.0)

    async with httpx.AsyncClient(timeout=http_timeout) as client:
        async with client.stream(
            "POST",
            CHAT_COMPLETIONS_URL,
            json=payload,
            headers=headers,
        ) as response:
            if response.status_code != 200:
                # Ne pas répercuter le corps du fournisseur au client ou dans les logs.
                raise RuntimeError(f"Fournisseur Hugging Face HTTP {response.status_code}")

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_text = line[6:].strip()
                if data_text == "[DONE]":
                    break
                try:
                    data = json.loads(data_text)
                    fragment = data["choices"][0]["delta"].get("content", "")
                except (ValueError, KeyError, IndexError, TypeError):
                    logger.debug("Fragment SSE Hugging Face ignoré (format inattendu).")
                    continue
                if fragment:
                    yield fragment
