# Llink — contrats HTTP

Les routes conservent les chemins et champs attendus par le frontend. Les règles d'accès, les limites et les codes HTTP sont détaillés dans [API_SECURITY.md](API_SECURITY.md).

## Disponibilité

### `GET /`

Réponse : `{"message": "Llink Backend API est opérationnel."}`.

## Compte et abonnement

### `GET /api/user/status`

Authorization facultative. Sans connexion, la réponse est `{"isValid": false, "expirationDate": null, "isNewUser": false}`. Un jeton présent mais invalide retourne 401.

### `POST /api/verify-payment`

Corps : `{"transactionId": "reference"}`. Authentification obligatoire. Réponse conservée : `{"success": false}` tant que l'API Think ne permet pas une vérification indépendante côté serveur.

## Chat

### `POST /api/chat`

Corps : `message` et `model` obligatoires ; `preferences`, `mode`, `source` et `data_collection_consent` facultatifs. Limite du message 12 000 caractères ; préférences 2 000 caractères.

Authorization facultative. Les sessions anonymes disposent d'un quota réduit ; un jeton invalide retourne 401. Réponse : streaming de fragments texte bruts au format historique `text/event-stream`.

## Médias

### `POST /api/ocr`

Corps JSON : `{"imageBase64": "data:image/jpeg;base64,..."}`. Authorization facultative. Images JPEG, PNG ou WebP uniquement, 6 Mo décodés maximum. Réponse : `{"response": "..."}`. Erreurs : 400, 413, 415, 429, 502 ou 503.

### `POST /api/audio`

Envoi multipart avec le champ fichier `file`. Authorization facultative. WebM, MP4, MP3, WAV, OGG et AAC acceptés, 12 Mo maximum. Réponse : `{"text": "..."}`. Erreurs : 400, 413, 415, 429, 502 ou 503.

## Historique

### `POST /api/history/sync`

Corps : objet conversation Dexie. Authentification obligatoire. Réponse : `{"status": "success"}` après écriture Firestore. Anonyme : 401.

### `GET /api/history`

Authentification obligatoire. Réponse : `{"chats": [...]}`. Anonyme : 401. Firestore indisponible : 503.
