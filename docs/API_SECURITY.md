# Configuration de sécurité — API Llink

## Variables de base

| Variable | Défaut | Description |
|---|---|---|
| \`APP_ENV\` | \`development\` hors Render ; \`production\` si \`RENDER=true\` | Le compteur mémoire est réservé à \`development\` et \`test\` ; \`staging\` et \`production\` exigent Firestore |
| \`FIREBASE_CONFIG\` | — | JSON du compte de service Firebase Admin, secret serveur |
| \`CORS_ORIGINS\` | Liste d'origines Llink autorisées | Liste CSV ; \`*\` est refusé |
| \`GEMINI_API_KEY\` | — | Clé Gemini pour VELORA et les fonctions média |
| \`ZAI_API_KEY\` | — | Clé API Z.ai pour SATORI et OMNIS |
| \`MINIMAX_API_KEY\` | — | Clé API MiniMax pour NOETRA |
| \`DEEPSEEK_API_KEY\` | — | Clé API DeepSeek pour AUREN |
| \`ZAI_BASE_URL\` | \`https://api.z.ai/api/paas/v4\` | Base URL de l'API Z.ai |
| \`MINIMAX_BASE_URL\` | \`https://api.minimax.io/v1\` | Base URL de l'API MiniMax |
| \`DEEPSEEK_BASE_URL\` | \`https://api.deepseek.com\` | Base URL de l'API DeepSeek |
| \`LLINK_HOURLY_CREDIT_LIMITS_USD\` | — | Budgets horaires facultatifs, objet JSON par niveau |
| `MAX_REQUEST_BODY_BYTES` | `27000000` | Taille totale maximale d'un corps HTTP |
| `MAX_ATTACHMENT_BYTES` | `10000000` | Taille maximale d'un fichier joint |
| `MAX_ATTACHMENT_TOTAL_BYTES` | `25000000` | Taille totale maximale des pièces jointes |
| `MAX_ATTACHMENT_FILES` | `5` | Nombre maximal de fichiers par message |
| \`MAX_IMAGE_BYTES\` | \`6000000\` | Taille image décodée maximale pour l'ancien endpoint OCR |
| \`MAX_AUDIO_BYTES\` | \`12000000\` | Taille audio maximale |
| \`MAX_MESSAGE_CHARS\` | \`12000\` | Taille maximale d'un prompt utilisateur |
| \`MAX_PREFERENCES_CHARS\` | \`2000\` | Taille maximale des préférences injectées |
| \`PROVIDER_TIMEOUT_SECONDS\` | \`60\` | Timeout fournisseur |
| \`AI_MAX_CONCURRENT\` | \`4\` | Requêtes IA simultanées par processus |
| \`AI_QUEUE_TIMEOUT_SECONDS\` | \`3\` | Temps maximal d'attente pour une place IA |

Les origines natives Capacitor autorisées par défaut sont \`capacitor://localhost\` (iOS) et \`https://localhost\` (Android avec le schéma Android par défaut de Capacitor 8). Elles restent des origines précises : aucun joker CORS n'est utilisé.

## Variables de quotas Phase 2

Chaque quota peut être surchargé séparément avec le préfixe \`QUOTA_ANON_\` ou \`QUOTA_USER_\`, suivi du nom de fonction et de \`_PER_MINUTE\` ou \`_PER_DAY\`.

Exemples :

- \`QUOTA_ANON_CHAT_PER_MINUTE=3\`
- \`QUOTA_ANON_CHAT_PER_DAY=20\`
- \`QUOTA_USER_CHAT_PER_MINUTE=12\`
- \`QUOTA_USER_CHAT_PER_DAY=240\`
- \`QUOTA_USER_OCR_PER_DAY=40\`
- \`QUOTA_USER_AUDIO_PER_DAY=20\`

Fonctions disponibles : \`CHAT\`, \`OCR\`, \`AUDIO\`, \`HISTORY_READ\`, \`HISTORY_SYNC\`, \`USER_STATUS\`, \`PAYMENT_VERIFY\`, \`USAGE_READ\`. Les quotas anonymes ne sont pas définis pour l'historique, le paiement ou la consommation, car ces routes exigent un compte.

Valeurs par défaut :

| Fonction | Anonyme / minute | Anonyme / UTC jour | Compte / minute | Compte / UTC jour |
|---|---:|---:|---:|---:|
| Chat | 3 | 20 | 12 | 240 |
| OCR | 1 | 5 | 5 | 40 |
| Audio | 1 | 3 | 3 | 20 |
| Pièces jointes | 2 | 10 | 5 | 30 |
| Live vocal/vidéo | — | — | 1 | 12 |
| Historique (lecture) | — | — | 30 | 200 |
| Historique (écriture) | — | — | 30 | 500 |
| État utilisateur | 3 | 20 | 30 | 300 |
| Vérification de paiement | — | — | 3 | 10 |
| Suppression d'historique | — | — | 20 | 100 |
| Export de données | — | — | 2 | 10 |
| Suppression de compte | — | — | 1 | 2 |
| Consommation (lecture) | — | — | 30 | 200 |

Les valeurs doivent être des entiers strictement positifs.

## Budgets horaires et registre Phase 3

La variable \`LLINK_HOURLY_CREDIT_LIMITS_USD\` accepte par exemple :

\`\`\`json
{"velora": 0.50, "satori": 2.00, "noetra": 5.00, "auren": 10.00, "omnis": 20.00}
\`\`\`

Ces valeurs illustrent uniquement la syntaxe : elles ne sont pas des plafonds recommandés et aucune n'est activée par défaut. En l'absence de variable, le backend mesure les coûts mais n'applique pas de blocage monétaire. Les quotas anti-abus de la Phase 2 restent actifs indépendamment.

Les réservations et coûts sont comptés sur une tranche horaire fixe UTC : de HH:00:00 à HH:59:59. Le serveur réserve un coût estimatif avant l'appel fournisseur ; à la fin, la mesure tokens du fournisseur remplace l'estimation. Si la mesure manque, la réservation est conservée comme coût prudent.

- Comptes : \`users/{uid}/usage_hours/{hour_bucket}\` et \`users/{uid}/usage_events/{request_id}\`.
- Anonymes : agrégat global \`system_usage_hours/{hour_bucket}\`, sans identifiant réseau brut.
- Les événements ne contiennent ni prompt, ni réponse, ni raisonnement, ni jeton d'authentification.
- \`GET /api/usage\` donne uniquement à l'utilisateur connecté ses compteurs de l'heure courante.
- Les coûts sont estimés à partir des tarifs publics de référence ; ils ne remplacent pas la facture du fournisseur.

## Droits d'accès aux niveaux

Le serveur ne se fie pas à \`level\`, \`model\` ou \`localStorage\` pour accorder un abonnement. Pour un compte payant, Firestore doit contenir \`isPro=true\`, une date \`expirationDate\` future et un \`subscriptionPlan\` reconnu (\`bronze\`, \`silver\`, \`gold\`, \`diamant\`). Les anciens documents sans \`subscriptionPlan\` retombent sur VELORA.

L'activation par paiement reste désactivée tant que l'intégration serveur-à-serveur de Think (Phase 7) n'est pas en place. Les clés fournisseur doivent être ajoutées dans les secrets du service Render existant avant d'activer les niveaux correspondants.

## Comportement de sécurité

- Les ID tokens Firebase sont vérifiés avec contrôle de révocation.
- L'export personnel, les suppressions d'historique et la suppression de compte sont réservés à un compte authentifié.
- La suppression de compte exige un auth_time de moins de 10 minutes et une confirmation explicite.
- Token absent : session anonyme uniquement sur les routes qui l'autorisent.
- Token présent mais invalide/expiré/révoqué : HTTP 401, sans repli anonyme.
- Firebase absent ou en panne sur une route privée : HTTP 503.
- Quota dépassé : HTTP 429 avec \`Retry-After\`.
- Niveau supérieur non autorisé : HTTP 403.
- Budget horaire configuré dépassé : HTTP 429 avec \`Retry-After\`.
- Corps ou pièce jointe trop volumineux : HTTP 413.
- Analyse des pièces jointes : 5 fichiers maximum, 10 Mo par fichier, 25 Mo au total, et 18 Mo pour les contenus multimédias transmis en ligne à Gemini.
- Format fichier non accepté : HTTP 415.
- Validation de schéma : HTTP 422.
- Panne fournisseur : message client générique.
- File IA saturée : HTTP 503.
- Firestore indisponible pour les compteurs de quotas : HTTP 503 en \`staging\` et \`production\`. Le compteur mémoire n'est jamais utilisé dans ces environnements.

## Firestore

Créer/autoriser la collection serveur \`api_rate_limits\`. Les écritures sont effectuées par Firebase Admin SDK côté serveur, dans une transaction. Les règles client Firestore ne doivent pas accorder aux clients un accès direct à cette collection.

Les documents de quotas ne conservent pas l'UID ou l'adresse IP en clair. Ils utilisent un identifiant de document SHA-256 dérivé du principal et du nom de la fonction ; les compteurs de minute et de jour sont remplacés dans le même document à chaque nouvelle période.

Le compte de service Firebase Admin doit également lire/écrire les sous-collections \`users/{uid}/usage_hours\`, \`users/{uid}/usage_events\` et la collection globale \`system_usage_hours\`. Les règles client ne doivent pas accorder d'accès direct au registre système anonyme.

Le compteur mémoire mono-processus est réservé à \`development\` et \`test\`.


## Quotas Phase 5

Les pièces jointes utilisent le scope `ATTACHMENT` : par défaut 2/minute et 10/jour pour les sessions anonymes, 5/minute et 30/jour pour les comptes. Les appels au chat qui suivent restent également soumis au quota CHAT.

Le Live utilise le scope `LIVE` : authentification obligatoire, 1 démarrage par minute et 12 par jour par compte. Une session est limitée à 10 minutes et occupe un créneau IA pendant sa durée. La clé Gemini reste exclusivement côté serveur.

Le coût Live est calculé à partir des compteurs de tokens par modalité renvoyés par Gemini. Au 1er novembre 2026, les prix Standard documentés sont de 3 USD/M tokens audio en entrée, 0,75 USD/M texte en entrée, 1 USD/M image/vidéo, 12 USD/M audio en sortie et 4,50 USD/M texte en sortie. Le taux de 21,60 USD/M correspond au tier Priority et n'est pas appliqué au compte Standard. Le taux audio sortie est surchargeable avec `LLINK_LIVE_AUDIO_OUTPUT_USD_PER_MILLION`.

## Quotas Phase 4

Les quotas utilisateur sont surchargeables par les variables suivantes :

- HISTORY_DELETE : QUOTA_USER_HISTORY_DELETE_PER_MINUTE et QUOTA_USER_HISTORY_DELETE_PER_DAY (défaut 20/minute, 100/jour).
- DATA_EXPORT : QUOTA_USER_DATA_EXPORT_PER_MINUTE et QUOTA_USER_DATA_EXPORT_PER_DAY (défaut 2/minute, 10/jour).
- ACCOUNT_DELETE : QUOTA_USER_ACCOUNT_DELETE_PER_MINUTE et QUOTA_USER_ACCOUNT_DELETE_PER_DAY (défaut 1/minute, 2/jour).

Ces quotas empêchent les suppressions et exports répétés d'être utilisés comme vecteur d'abus. Ils sont stockés dans api_rate_limits et purgés avec les autres compteurs lors de la suppression du compte.
