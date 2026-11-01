## Phase 5 — Live et Markdown

La conversation Live est relayée par `WS /ws/live` via FastAPI et le SDK officiel `google-genai`.

- Modèle : `gemini-3.1-flash-live-preview`.
- Audio entrant : PCM16 mono 16 kHz.
- Audio sortant : PCM 24 kHz, lu en continu via Web Audio.
- Vidéo : image JPEG à un maximum d'une image par seconde.
- Transcription dans les deux directions, texte direct et interruptions.
- Firebase ID token obligatoire ; le navigateur n'obtient jamais la clé Gemini.
- Quota : 1 démarrage par minute et 12 démarrages par jour par compte.
- Durée d'une session : 10 minutes maximum.
- Une réservation de budget est faite avant l'ouverture de la session ; les coûts sont régularisés avec `usage_metadata` et les compteurs de modalités de Gemini.

Le prix de sortie audio Live est configurable par `LLINK_LIVE_AUDIO_OUTPUT_USD_PER_MILLION`. La valeur par défaut est 12 USD/M tokens au 1er novembre 2026. Google a annoncé une évolution au 1er janvier 2027 : actualiser la variable Render avant cette date.

Le rendu des messages est géré par Marked (GitHub Flavored Markdown) et filtré par DOMPurify. Les deux dépendances sont chargées depuis jsDelivr en version épinglée ; un rendu texte sécurisé de secours est disponible lorsque le CDN est inaccessible.

Le Live nécessite HTTPS, Internet, une session Firebase valide, une clé Gemini côté serveur et un accès microphone/caméra autorisé par l'appareil. La recette de bout en bout avec Render et Gemini n'a pas été réalisée par les seuls tests unitaires.