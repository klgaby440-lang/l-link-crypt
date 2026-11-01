# Configuration de sécurité — API Llink

## Variables de base

| Variable | Description |
|---|---|
| \`APP_ENV\` | \`development\`, \`test\`, \`staging\` ou \`production\` |
| \`FIREBASE_CONFIG\` | JSON du compte de service Firebase Admin, secret serveur |
| \`CORS_ORIGINS\` | Liste CSV d'origines précises ; \`*\` est refusé |
| \`GEMINI_API_KEY\` | Clé Gemini VELORA et fonctions média |
| \`ZAI_API_KEY\` | Clé API Z.ai pour SATORI et OMNIS |
| \`MINIMAX_API_KEY\` | Clé API MiniMax pour NOETRA |
| \`DEEPSEEK_API_KEY\` | Clé API DeepSeek pour AUREN |
| \`ZAI_BASE_URL\` | Défaut : \`https://api.z.ai/api/paas/v4\` |
| \`MINIMAX_BASE_URL\` | Défaut : \`https://api.minimax.io/v1\` |
| \`DEEPSEEK_BASE_URL\` | Défaut : \`https://api.deepseek.com\` |
| \`LLINK_HOURLY_CREDIT_LIMITS_USD\` | Budgets horaires par niveau, objet JSON optionnel |
| \`MAX_REQUEST_BODY_BYTES\` | 13 500 000 octets par défaut |
| \`MAX_IMAGE_BYTES\` | 6 000 000 octets décodés par défaut |
| \`MAX_AUDIO_BYTES\` | 12 000 000 octets par défaut |
| \`MAX_MESSAGE_CHARS\` | 12 000 caractères par défaut |
| \`MAX_PREFERENCES_CHARS\` | 2 000 caractères par défaut |
| \`PROVIDER_TIMEOUT_SECONDS\` | 60 secondes par défaut |
| \`AI_MAX_CONCURRENT\` | 4 requêtes simultanées par processus |
| \`AI_QUEUE_TIMEOUT_SECONDS\` | 3 secondes maximum |

Les origines natives Capacitor autorisées par défaut sont \`capacitor://localhost\` et \`https://localhost\`. Elles restent des origines précises.

## Budgets et registre de consommation

La variable \`LLINK_HOURLY_CREDIT_LIMITS_USD\` accepte, par exemple :

\`\`\`json
{"velora": 0.50, "satori": 2.00, "noetra": 5.00, "auren": 10.00, "omnis": 20.00}
\`\`\`

Ces valeurs sont un exemple de syntaxe, pas des plafonds recommandés ou activés par défaut. La configuration absente signifie **mesure sans blocage par budget monétaire**. Les quotas anti-abus de la Phase 2 restent actifs indépendamment.

Les réservations et coûts sont comptés sur une tranche horaire fixe UTC : de HH:00:00 à HH:59:59. Le serveur réserve un coût estimatif avant l'appel fournisseur ; à la fin, la mesure tokens du fournisseur remplace l'estimation. Si la mesure n'est pas fournie, la réservation est conservée comme coût prudent.

- Comptes : \`users/{uid}/usage_hours/{hour_bucket}\` et \`users/{uid}/usage_events/{request_id}\`.
- Anonymes : agrégat global \`system_usage_hours/{hour_bucket}\`, sans identifiant réseau brut.
- Les événements ne contiennent ni prompt, ni réponse, ni jeton d'authentification.
- \`GET /api/usage\` donne uniquement à l'utilisateur connecté ses compteurs de l'heure courante.
- Les coûts sont une estimation à partir des tarifs publics de référence ; ils ne remplacent pas la facture du fournisseur.

## Droits d'accès aux niveaux

Le serveur ne se fie pas à \`level\`, \`model\` ou \`localStorage\` pour accorder un abonnement. Pour un compte payant, Firestore doit contenir \`isPro=true\`, une date \`expirationDate\` future et un \`subscriptionPlan\` reconnu (\`bronze\`, \`silver\`, \`gold\`, \`diamant\`). Les anciens documents sans \`subscriptionPlan\` retombent sur VELORA.

L'activation par paiement reste désactivée tant que l'intégration serveur-à-serveur de Think (Phase 7) n'est pas en place. Les clés fournisseur doivent être ajoutées dans les secrets Render avant d'activer les niveaux correspondants.

## Comportement de sécurité

- Token Firebase absent : routes anonymes uniquement.
- Token présent mais invalide/expiré/révoqué : HTTP 401, sans repli anonyme.
- Firebase absent ou en panne sur une route privée : HTTP 503.
- Quota dépassé : HTTP 429 avec \`Retry-After\`.
- Niveau supérieur non autorisé : HTTP 403.
- Budget horaire configuré dépassé : HTTP 429 avec \`Retry-After\`.
- Registre Firestore indisponible : HTTP 503 en staging/production.
- Corps trop volumineux : HTTP 413 ; média non accepté : HTTP 415.

En développement/tests uniquement, un compteur quota mémoire est permis. En staging et production, les quotas requièrent Firestore.

## Firestore

Le compte de service Firebase Admin doit lire/écrire les documents des utilisateurs, \`api_rate_limits\`, les sous-collections \`usage_hours\` et \`usage_events\`, ainsi que la collection globale \`system_usage_hours\`. Les règles client ne doivent pas accorder d'accès direct aux compteurs de quotas ou au registre système anonyme.
