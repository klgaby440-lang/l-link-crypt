"""Adaptateur SSE commun aux fournisseurs exposant Chat Completions OpenAI-compatible."""

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    cached_input_tokens: int = 0


@dataclass(frozen=True)
class ProviderEvent:
    text: str | None = None
    usage: TokenUsage | None = None


def _read_field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def parse_usage(value: Any) -> TokenUsage | None:
    if not value:
        return None
    prompt = _read_field(value, "prompt_tokens")
    completion = _read_field(value, "completion_tokens")
    if prompt is None or completion is None:
        return None
    details = _read_field(value, "prompt_tokens_details", {})
    cached = _read_field(details, "cached_tokens", 0) or 0
    try:
        return TokenUsage(
            prompt_tokens=max(0, int(prompt)),
            completion_tokens=max(0, int(completion)),
            cached_input_tokens=max(0, int(cached)),
        )
    except (TypeError, ValueError):
        return None


def parse_stream_payload(payload: dict[str, Any]) -> ProviderEvent:
    """Lit le texte final visible et ignore les champs de raisonnement internes."""
    usage = parse_usage(payload.get("usage"))
    choices = payload.get("choices") or []
    if not choices:
        return ProviderEvent(usage=usage)

    delta = (choices[0] or {}).get("delta") or {}
    content = delta.get("content")
    if isinstance(content, str):
        return ProviderEvent(text=content or None, usage=usage)
    if isinstance(content, list):
        pieces = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        combined = "".join(piece for piece in pieces if isinstance(piece, str))
        return ProviderEvent(text=combined or None, usage=usage)
    return ProviderEvent(usage=usage)


def _reasoning_parameters(provider: str, effort: str) -> dict[str, Any]:
    mapped = {
        "normal": "low",
        "extra": "high",
        "ultime": "max",
    }.get(effort, "low")
    if provider == "deepseek":
        return {
            "reasoning_effort": mapped,
            "thinking": {"type": "disabled" if effort == "normal" else "enabled"},
        }
    if provider == "minimax":
        # M3.1-Flash always reasons; reduce/increase its effort rather than disabling it.
        return {"reasoning_effort": mapped}
    if provider == "zai":
        # GLM-4.7-Flash and GLM-5 accept the thinking switch, not reasoning_effort.
        return {"thinking": {"type": "disabled" if effort == "normal" else "enabled"}}
    return {}


async def stream_openai_compatible(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model_id: str,
    system_instruction: str,
    user_text: str,
    effort: str,
    max_output_tokens: int,
    timeout_seconds: int,
) -> AsyncIterator[ProviderEvent]:
    """Émet les fragments visibles et la consommation token fournie dans le flux SSE."""
    endpoint = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": max_output_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    payload.update(_reasoning_parameters(provider, effort))
    if provider == "minimax":
        payload.update({"temperature": 1.0, "top_p": 0.95})
    elif provider == "zai":
        payload["temperature"] = 0.7
    # DeepSeek reasoning mode does not use temperature.

    timeout = httpx.Timeout(
        timeout_seconds,
        connect=min(10.0, float(timeout_seconds)),
        write=15.0,
        pool=5.0,
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            endpoint,
            json=payload,
            headers=headers,
        ) as response:
            if response.status_code != 200:
                # Ne pas logger ni renvoyer les corps de réponse fournisseurs.
                raise RuntimeError(f"{provider} provider HTTP {response.status_code}")

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_text = line[5:].strip()
                if not data_text:
                    continue
                if data_text == "[DONE]":
                    break
                try:
                    parsed = json.loads(data_text)
                except (ValueError, TypeError):
                    logger.debug("Fragment SSE ignoré pour le fournisseur %s.", provider)
                    continue
                if isinstance(parsed, dict):
                    event = parse_stream_payload(parsed)
                    if event.text or event.usage:
                        yield event
