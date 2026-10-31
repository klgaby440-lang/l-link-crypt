# Configuration de sécurité — API Llink

## Variables de base

| Variable | Défaut | Description |
|---|---|---|
| `APP_ENV` | `development` hors Render ; `production` si `RENDER=true` | L'absence de Firestore est tolérée en développement uniquement |
| `FIREBASE_CONFIG` | — | JSON du compte de service Firebase Admin, secret côté serveur |
| `CORS_ORIGINS` | Liste de domaines Llink autorisés | Liste CSV ; `*` est refusé |
| `MAX_REQUEST_BODY_BYTES` | `13500000` | Taille totale maximale d'un corps HTTP |
| `MAX_IMAGE_BYTES` | `6000000` | Taille image décodée maximale |
| `MAX_AUDIO_BYTES` | `12000000` | Taille audio maximale |
| `MAX_MESSAGE_CHARS` | `12000` | Taille maximale d'un prompt utilisateur |
| `MAX_PREFERENCES_CHARS` | `2000` | Taille maximale des préférences injectées |
| `PROVIDER_TIMEOUT_SECONDS` | `60` | Timeout Gemini/Hugging Face |
| `AI_MAX_CONCURRENT` | `4` | Requêtes IA simultanées par processus |
| `AI_QUEUE_TIMEOUT_SECONDS` | `3` | Temps maximal d'attente pour une place IA |

## Variables de quotas

Chaque quota peut être surchargé séparément avec le préfixe `QUOTA_ANON_` ou `QUOTA_USER_`, suivi du nom de fonction et de `_PER_MINUTE` ou `_PER_DAY`.

Exemples :

- `QUOTA_ANON_CHAT_PER_MINUTE=3`
- `QUOTA_ANON_CHAT_PER_DAY=20`
- `QUOTA_USER_CHAT_PER_MINUTE=12`
- `QUOTA_USER_CHAT_PER_DAY=240`
- `QUOTA_USER_OCR_PER_DAY=40`
- `QUOTA_USER_AUDIO_PER_DAY=20`

Fonctions disponibles : `CHAT`, `OCR`, `AUDIO`, `HISTORY_READ`, `HISTORY_SYNC`, `USER_STATUS`, `PAYMENT_VERIFY`. Les quotas anonymes ne sont pas définis pour l'historique et les paiements, car ces routes exigent un compte.

Les valeurs doivent être des entiers strictement positifs.

## Comportement de sécurité

- Les ID tokens Firebase sont vérifiés avec contrôle de révocation et d'état désactivé.
- Token absent : session anonyme uniquement sur les routes qui l'autorisent.
- Token présent mais invalide : HTTP 401, sans repli anonyme.
- Firebase absent ou en panne : HTTP 503 sur les routes nécessitant une identité.
- Quota dépassé : HTTP 429, en-tête `Retry-After`.
- Corps trop volumineux : HTTP 413.
- Format fichier non accepté : HTTP 415.
- Validation de schéma : HTTP 422.
- Panne fournisseur : HTTP 502 avec message générique.
- File IA saturée : HTTP 503.

## Firestore

Créer/autoriser la collection serveur `api_rate_limits`. Les écritures sont effectuées par Firebase Admin SDK côté serveur, dans une transaction. Les règles client Firestore ne doivent pas accorder aux clients un accès direct à cette collection.

Les documents de quotas ne conservent pas l'UID ou l'adresse IP en clair. Ils utilisent un identifiant de document SHA-256 dérivé du principal et du nom de la fonction ; les compteurs de minute et de jour sont remplacés dans le même document à chaque nouvelle période.
