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
- \`preferences\`, \`mode\`, \`source\`, \`source_language\`, \`target_language\` et \`data_collection_consent\` facultatifs. En mode \`translate\`, les champs de langue sont des codes ISO/BCP 47 transmis au backend ; le serveur construit l'instruction de traduction dans la paire demandée.

Limite du message : 12 000 caractères ; préférences : 2 000 caractères. Le champ history accepte jusqu'à 24 tours antérieurs, chacun avec role (user, assistant ou ancien bot) et text. Le backend ne transmet que les 20 tours les plus récents et limite l'historique à 32 000 caractères pour contenir les coûts ; le message courant reste séparé.

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


### \`POST /api/chat/attachments\`

Envoi multipart avec un champ \`files\` répété (plusieurs fichiers) et les champs de chat \`message\`, \`history\` (JSON), \`model\`, \`level\`, \`effort\`, \`mode\`, \`preferences\` et \`source\`. La réponse réutilise le flux \`text/event-stream\` de \`POST /api/chat\`.

- Jusqu'à 5 fichiers par message.
- 10 Mo par fichier, 25 Mo au total ; valeurs configurables côté serveur.
- PDF, images JPEG/PNG/WebP/BMP/HEIC/HEIF, audio et vidéo : analyse multimodale Gemini, puis synthèse transmise au modèle sélectionné dans Llink.
- TXT, Markdown, CSV, JSON, XML, HTML, code, DOCX, XLSX et PPTX : extraction de texte côté serveur.
- Les autres formats restent acceptés par le sélecteur et peuvent être joints ; tant qu'un extracteur n'existe pas, leur nom et leur type sont transmis au modèle avec une indication explicite que le contenu n'a pas été lu.
- Les médias binaires combinés sont plafonnés à 18 Mo pour l'analyse inline Gemini.
- La route applique un quota spécifique, le contrôle d'accès au niveau de chat, le budget de coût, et les limites de taille. Les appels de chat et de fournisseur restent suivis séparément.

Les fichiers binaires ne sont pas ajoutés à Firestore. L'historique conserve les métadonnées de pièce jointe côté client, tandis que le contenu extrait est envoyé uniquement dans la requête IA initiée par l'utilisateur.

## Historique

### \`POST /api/history/sync\`

Corps : objet conversation Dexie avec un champ syncId stable et messages. Authentification obligatoire. La clé syncId identifie le document Firestore. Réponse : \`{"status": "success"}\` après écriture Firestore. Anonyme : 401.

### \`GET /api/history\`

Authentification obligatoire. Réponse : \`{"chats": [...]}\`. Anonyme : 401. Firestore indisponible : 503. Chaque conversation retournée inclut cloud_id et syncId pour la réconciliation locale ; le frontend importe les conversations distantes dans IndexedDB lorsqu'elles ne sont pas déjà présentes.


## Confidentialité, export et suppressions — Phase 4

### GET /api/data/export

Authentification obligatoire. Télécharge un JSON contenant le document de compte, l'ensemble de ses sous-collections Firestore (dont l'historique et les compteurs d'usage) ainsi que les anciens enregistrements de global_datasets encore explicitement liés à l'UID. La réponse utilise Content-Disposition: attachment et Cache-Control: no-store.

Le frontend ajoute à ce fichier les conversations et préférences personnelles présentes sur l'appareil courant. Les données locales d'un autre appareil ne sont pas incluses par l'export cloud.

### DELETE /api/history/{sync_id}

Authentification obligatoire. Supprime une seule conversation de users/{uid}/chats/{sync_id}. La suppression est idempotente : une référence déjà absente retourne également un statut deleted. Le compte connecté détermine le propriétaire ; un client ne peut pas cibler les discussions d'un autre compte.

### DELETE /api/history

Authentification obligatoire. Supprime toutes les conversations cloud du compte connecté. Réponse : {"status":"deleted","deleted_count":0} (le compteur représente les documents supprimés).

Sur l'appareil, les suppressions effectuées hors ligne sont conservées comme tombstones Dexie, liés à l'UID propriétaire. À la prochaine connexion au même compte, elles sont envoyées au serveur avant la restauration de l'historique, afin d'éviter la réapparition d'une conversation supprimée.

### DELETE /api/account

Authentification obligatoire et confirmation JSON exacte : {"confirmation":"SUPPRIMER MON COMPTE"}. Le jeton Firebase doit avoir été authentifié dans les 10 dernières minutes (auth_time), sinon l'API répond 401 et demande une reconnexion récente.

Le backend supprime récursivement l'arbre Firestore users/{uid}, les compteurs pseudonymisés correspondants de api_rate_limits, les anciens documents d'amélioration encore liés à l'UID, puis le compte Firebase Auth. Une erreur interrompt le parcours avec 503 ; les suppressions déjà effectuées ne sont pas recréées et une nouvelle tentative est possible tant que Firebase Auth existe encore.

Le client efface ensuite l'historique et les préférences personnelles locales de cet appareil, puis termine la session.
