# Llink — contrats HTTP

Les chemins existants restent compatibles avec le frontend. Les règles d'accès et les limites sont détaillées dans [API_SECURITY.md](API_SECURITY.md).

## Disponibilité

### \`GET /\`

Réponse : \`{"message": "Llink Backend API est opérationnel."}\`.

## Compte et abonnement

### \`GET /api/user/status\`

Authorization facultative. Sans connexion, la réponse est \`{"isValid": false, "expirationDate": null, "isNewUser": false}\`. Un jeton présent mais invalide retourne 401.

### \`POST /api/verify-payment\`

Corps : \`{"transactionId": "reference"}\`. Authentification obligatoire. Réponse conservée : \`{"success": false}\` tant que l'API Think ne permet pas une vérification indépendante côté serveur.

## Chat

### \`POST /api/chat\`

Corps :

- \`message\` et \`model\` obligatoires ; \`model\` est conservé pour compatibilité.
- \`level\` facultatif : \`velora\`, \`satori\`, \`noetra\`, \`auren\`, \`omnis\`.
- \`effort\` facultatif : \`normal\`, \`extra\`, \`ultime\`.
- \`preferences\`, \`mode\`, \`source\` et \`data_collection_consent\` facultatifs.

Limite du message : 12 000 caractères ; préférences : 2 000 caractères.

Authorization facultative. Les sessions anonymes restent limitées à VELORA. Le serveur résout le niveau réel depuis Firestore et ne fait pas confiance au niveau envoyé par le navigateur. Un niveau supérieur au droit du compte retourne 403. Une configuration fournisseur manquante retourne 503 avant ouverture du flux.

La réponse réussie reste un flux de fragments texte bruts au format historique \`text/event-stream\`. Les événements de raisonnement privés des fournisseurs ne sont jamais transmis au frontend.

### Routage du registre Phase 3

| Niveau | Fournisseur | Modèle API |
|---|---|---|
| VELORA | Google Gemini | \`gemini-3.5-flash-lite\` |
| SATORI | Z.ai | \`glm-4.7-flash\` |
| NOETRA | MiniMax | \`MiniMax-M3.1-Flash\` |
| AUREN | DeepSeek | \`deepseek-flash\` |
| OMNIS | Z.ai | \`glm-5\` |

Les alias historiques de \`model\` restent acceptés si \`level\` est absent. Dès que \`level\` est fourni, l'identifiant du modèle vient exclusivement du registre serveur.

## Consommation et crédits

### \`GET /api/usage\`

Authentification obligatoire. Retourne les compteurs de la tranche horaire UTC courante : \`level\`, \`hour_started_at\`, \`reset_at\`, \`request_count\`, compteurs de tokens, coût USD estimé, réservation en cours et budget/restant éventuels.

Les coûts sont calculés avec le tarif de référence du registre et les tokens de consommation renvoyés par le fournisseur. Si un fournisseur ne renvoie pas sa consommation, le coût réservé à l'avance est comptabilisé par prudence.

La réponse n'expose aucun prompt, aucune réponse, aucune clé fournisseur et aucun raisonnement interne.

## Médias

### \`POST /api/ocr\`

Corps JSON : \`{"imageBase64": "data:image/jpeg;base64,..."}\`. Authorization facultative. Images JPEG, PNG ou WebP uniquement, 6 Mo décodés maximum. Réponse : \`{"response": "..."}\`. Erreurs : 400, 413, 415, 429, 502 ou 503.

### \`POST /api/audio\`

Envoi multipart avec le champ fichier \`file\`. Authorization facultative. WebM, MP4, MP3, WAV, OGG et AAC acceptés, 12 Mo maximum. Réponse : \`{"text": "..."}\`. Erreurs : 400, 413, 415, 429, 502 ou 503.

## Historique

### \`POST /api/history/sync\`

Corps : objet conversation Dexie. Authentification obligatoire. Réponse : \`{"status": "success"}\` après écriture Firestore. Anonyme : 401.

### \`GET /api/history\`

Authentification obligatoire. Réponse : \`{"chats": [...]}\`. Anonyme : 401. Firestore indisponible : 503.
