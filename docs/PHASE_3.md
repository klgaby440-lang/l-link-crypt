# Phase 3 — Registre de modèles, routage et mesure des crédits

**Branche :** \`phase-3/model-registry-usage-ledger\`  
**Base :** dernier \`main\` au début des travaux Phase 3  
**Objectif :** faire du backend l'unique autorité pour le routage IA, les droits d'accès et la mesure de consommation.

## 1. Registre de modèles

| Niveau Llink | Fournisseur | Modèle API | Entrée / sortie / entrée mise en cache (USD par million de tokens) |
|---|---|---|---:|
| VELORA | Google Gemini | \`gemini-3.5-flash-lite\` | 0,30 $ / 2,50 $ |
| SATORI | Z.ai | \`glm-4.7-flash\` | 0 $ / 0 $ (tarif public affiché gratuit à la date de vérification) |
| NOETRA | MiniMax | \`MiniMax-M3.1-Flash\` | 0,15 $ / 0,60 $ |
| AUREN | DeepSeek | \`deepseek-flash\` | 0,30 $ / 1,20 $ (tarif peak retenu) |
| OMNIS | Z.ai | \`glm-5\` | 1,00 $ / 3,20 $ |

Le tarif d'entrée mis en cache est stocké séparément dans le registre. Les prix sont des références publiques observées le 1er novembre 2026 et peuvent évoluer. Voir les sources fournisseur à la fin de ce document.

Les fournisseurs sont appelés directement, avec un adaptateur SSE compatible Chat Completions lorsque c'est pertinent. Le fait qu'un modèle existe sur Hugging Face ne signifie pas qu'il est hébergé par le Hugging Face Inference Router. Aucun basculement silencieux vers un modèle différent n'est fait.

## 2. Compatibilité des requêtes

Le frontend transmet déjà \`level\` et \`effort\`. Le schéma backend les accepte maintenant :
- niveaux : \`velora\`, \`satori\`, \`noetra\`, \`auren\`, \`omnis\`;
- intensité : \`normal\`, \`extra\`, \`ultime\`.

Le champ historique \`model\` reste accepté. Si \`level\` est absent, les anciens alias sont traduits par le registre. Si \`level\` est présent, le modèle est résolu uniquement côté serveur.

Les anciens endpoints et le streaming texte brut restent présents. Les champs \`reasoning_content\` et autres contenus de raisonnement internes ne sont jamais affichés à l'utilisateur.

## 3. Droits et abonnement

L'autorisation est lue sur le document Firestore du compte : \`isPro\`, \`expirationDate\` et \`subscriptionPlan\`. Bronze ouvre SATORI, Silver NOETRA, Gold AUREN et Diamant OMNIS ; chaque palier comprend les niveaux inférieurs.

Un compte anonyme ou non abonné reste VELORA. Les documents payants historiques sans \`subscriptionPlan\` restent aussi VELORA. C'est volontaire : le navigateur ne peut pas s'accorder un abonnement en modifiant son stockage local.

**Limite actuelle :** l'API de paiement retourne toujours \`success=false\`. Le remplissage de \`subscriptionPlan\` par une confirmation serveur Think relève de la Phase 7. Les niveaux payants nécessitent donc encore une activation de paiement vérifiée avant de pouvoir être utilisés en production.

## 4. Mesure horaire

Les appels sont mesurés par tranche fixe UTC :
- réserve du coût estimé avant l'appel ;
- enregistrement des tokens d'entrée, de sortie et mis en cache ;
- calcul du coût estimé en micro-USD à partir du tarif du registre ;
- règlement de la réserve quand le fournisseur a fini ;
- si la consommation fournisseur manque, la réserve est conservée pour ne pas sous-estimer le coût.

Les utilisateurs connectés sont comptabilisés dans leurs sous-collections Firestore. Les anonymes sont comptabilisés dans un agrégat horaire global sans IP brute. Aucun prompt, aucune réponse et aucun raisonnement ne sont stockés dans le registre de consommation.

L'endpoint authentifié \`GET /api/usage\` retourne les tokens et coûts de l'heure courante.

## 5. Plafonds horaires configurables

Le plafond par niveau peut être défini par \`LLINK_HOURLY_CREDIT_LIMITS_USD\`, par exemple :

\`\`\`json
{"velora": 0.50, "satori": 2.00, "noetra": 5.00, "auren": 10.00, "omnis": 20.00}
\`\`\`

Ce JSON illustre uniquement la syntaxe : **aucune valeur n'est activée par défaut**. Les plafonds monétaires nécessitent une décision CRYPT fondée sur les coûts réels, les marges et la politique de crédits. En attendant, le registre mesure la dépense et les quotas de sécurité Phase 2 restent actifs. Pour les anonymes, le plafond VELORA éventuel est global à l'heure ; pour les utilisateurs connectés, il est par compte.

## 6. Configuration opérateur

Avant d'ouvrir les modèles correspondants, ajouter les secrets suivants au service Render existant :
- \`GEMINI_API_KEY\`
- \`ZAI_API_KEY\`
- \`MINIMAX_API_KEY\`
- \`DEEPSEEK_API_KEY\`

Le backend retourne 503 si le fournisseur du niveau demandé n'est pas configuré. Aucun fournisseur secondaire n'est appelé automatiquement.

Le compte Firebase Admin doit avoir les droits de lecture/écriture sur \`users/{uid}/usage_hours\`, \`users/{uid}/usage_events\`, \`system_usage_hours\` et \`api_rate_limits\`.

## 7. Limites connues / validation restante

- Les prix sont des références publiques et non un rapprochement de facture.
- Les niveaux payants sont verrouillés tant que Think ne remplit pas \`subscriptionPlan\`.
- Les plafonds horaires restent désactivés jusqu'à validation des montants par CRYPT.
- Gemini utilise le SDK officiel `google-genai` ; les intensités `normal`, `extra` et `ultime` sont traduites en niveaux de réflexion Gemini `minimal`, `medium` et `high`. L'adaptateur convertit aussi les anciennes parts multimédias utilisées par OCR/audio.
- Les tests automatisés simulent les fournisseurs et Firestore ; ils ne remplacent pas une requête de recette avec les clés réelles.
- Ne pas déployer ou activer de clés en production avant revue de cette PR.

## Sources tarifaires et d'API

- [Gemini 3.5 Flash-Lite — modèle et tarif](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)
- [Z.ai — page tarifaire](https://docs.z.ai/guides/overview/pricing)
- [MiniMax M3.1 Flash — modèle et réglages](https://huggingface.co/MiniMaxAI/MiniMax-M3.1-Flash)
- [DeepSeek — API Chat Completions et modèles](https://api-docs.deepseek.com/api/create-chat-completion/)
- [DeepSeek — mode de réflexion](https://api-docs.deepseek.com/guides/thinking_mode/)
- [MiniMax — API texte](https://platform.minimax.io/docs/guides/text-generation)
