"""Adaptateur Gemini avec plafond de sortie et délai d'attente explicite."""

import google.generativeai as genai

from llink_api.config import get_settings


MODEL_NAME = "gemini-2.5-flash"


def get_gemini_model(system_instruction: str | None = None):
    """Retourne un modèle Gemini configuré ou signale une configuration absente."""
    api_key = get_settings().gemini_api_key
    if not api_key:
        raise RuntimeError("Clé API Gemini manquante sur le serveur.")

    genai.configure(api_key=api_key)
    return genai.GenerativeModel(
        model_name=MODEL_NAME,
        system_instruction=system_instruction,
        generation_config={"max_output_tokens": 2048},
    )
