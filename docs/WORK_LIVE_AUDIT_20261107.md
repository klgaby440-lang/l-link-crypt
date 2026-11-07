# Audit technique — Llink Work et Live
Date : 7 novembre 2026
Branche d'analyse : `main` au commit `d5f5332d55f51471a770047e4e340d03d01ffe66`
Branche de travail UI : `feature/work-live-interface-refresh-20261107`

## Résumé exécutif

Work dispose déjà d'un vrai agent outillé, d'un flux d'événements, d'éditeurs et d'une architecture locale/cloud. Le principal écart fonctionnel concerne la persistance distante des fichiers binaires : documents Word, classeurs Excel, présentations, PDF et images restent locaux, même lorsque l'utilisateur est connecté.

Live possède un relais WebSocket authentifié vers Gemini Live, avec audio PCM bidirectionnel, transcription, interruptions, caméra et comptabilisation de l'usage. Dans la version de `main` auditée, le mode vocal principal n'utilisait cependant pas ce relais : seul le panneau d'appel vidéo l'ouvrait. Le flux audio standard et le flux Live temps réel étaient donc deux expériences techniques différentes.

La branche UI remédie à ce dernier point : l'écran vocal initialise désormais la même session WebSocket, le micro est commandé depuis l'écran vocal, et un seul canvas 3D est déplacé entre l'écran vocal et l'appel vidéo. La configuration Live de la branche active aussi la compression glissante du contexte. Ces changements doivent encore passer par une validation navigateur et les workflows CI.

## 1. Mode Live

### Architecture actuelle observée

- Frontend : `app/index.html`.
- Backend : `llink_api/api/routes/live.py`, WebSocket `/ws/live`.
- Fournisseur : SDK Python `google-genai`, modèle configuré `gemini-3.8-live`.
- Authentification : le navigateur transmet un Firebase ID token au premier événement WebSocket ; le serveur le vérifie avant d'ouvrir la session fournisseur.
- Audio entrant : PCM16 mono, 16 kHz.
- Audio sortant : PCM, 24 kHz, décodé et planifié par Web Audio.
- Transcriptions utilisateur et assistant : retransmises au navigateur.
- Vidéo : JPEG, image de caméra au plus toutes les secondes dans le client actuel.
- Limites serveur : bloc audio jusqu'à 48 Ko, image jusqu'à 750 Ko, texte utilisateur jusqu'à 8 000 caractères, 40 000 caractères par session, durée serveur maximale de 600 secondes.
- Quota déclaré : 1 démarrage par minute et 12 par jour, par compte.
- La clé Gemini reste côté serveur ; elle n'est pas transmise au navigateur.

### Points forts

- Le navigateur ne détient pas la clé API fournisseur.
- Le token Firebase est vérifié avant de créer la session.
- Les chunks audio et image sont validés en Base64 et limités en taille.
- Les événements d'interruption arrêtent immédiatement les nœuds audio en lecture.
- Le coût réel est réglé à la fermeture à partir des compteurs de modalités retournés par le fournisseur.
- Le client ferme la caméra, le microphone, les timers et les contextes audio lorsqu'il met fin à la session.

### Problèmes et améliorations prioritaires

**L1 — Deux chemins Live différents dans `main`.** Le mode vocal principal affiche une animation d'ondes et utilise l'ancien `handleVoice()`. Le WebSocket `/ws/live` n'est lancé que par `openLiveVideoCall()`. Cela produit deux expériences de conversation distinctes et empêche le mode audio simple de bénéficier de la session native temps réel.  
État branche UI : raccordement du mode vocal au WebSocket commun, avec bouton micro dédié et réutilisation de la session quand le panneau vidéo s'ouvre ou se ferme.

**L1 — Durée et reprise de session.** Le serveur ferme sa session à 600 secondes. La documentation Google indique qu'une connexion Live reste limitée à environ 10 minutes et prévoit des messages `GoAway` ainsi que des handles de reprise. Le code actuel ne conserve pas de handle de reprise et ne rétablit pas la session après une coupure. Le plafond local se trouve donc exactement au voisinage de la limite fournisseur.  
À faire : gérer `GoAway`, mémoriser `session_resumption_update`, reconnecter côté serveur et reprendre la session sans perdre le fil conversationnel. Tant que cette reprise n'est pas implémentée, clôturer avec une marge avant l'expiration fournisseur.

**L1 — Compression du contexte.** `main` ne configure pas de compression de contexte alors que la conversation accumule continuellement les tokens audio et vidéo. La documentation Live recommande `ContextWindowCompressionConfig` et une fenêtre glissante pour les longues sessions.  
État branche UI : ajout de `context_window_compression.sliding_window` dans `build_live_config()` et d'une assertion dans `tests/test_live.py`. Le support doit être confirmé par le workflow backend et une session fournisseur réelle.

**L1 — Taille des blocs micro.** Le client utilise `ScriptProcessor`, une API Web Audio dépréciée. Le buffer initial de 4 096 échantillons à 16 kHz représentait environ 256 ms ; la branche le réduit à 2 048, environ 128 ms. La recommandation Google est de transmettre des blocs de 20 à 40 ms pour limiter la latence.  
À faire : remplacer progressivement `ScriptProcessor` par `AudioWorklet` et émettre des blocs PCM de 320 à 640 échantillons à 16 kHz, avec un chemin de secours pour les navigateurs incompatibles.

**L1 — Budget pré-réservé potentiellement dissuasif.** Le backend réserve le budget avant chaque session avec un prompt artificiel de 380 000 caractères. La fonction `estimate_request_cost_microusd` estime `ceil(longueur / 2) + 256` tokens d'entrée et ajoute le plafond de sortie configuré à 15 000 tokens. Avec les tarifs configurés dans `LIVE_USAGE_MODEL`, cela réserve environ 750 768 micro-dollars, soit 0,750768 USD, par ouverture de session, avant régularisation du coût réel.  
À faire : établir une estimation fondée sur la durée réellement autorisée, le type de session (audio seul ou audio/vidéo), les tokens de sortie et les plafonds de crédit ; vérifier le comportement des abonnements dont le budget horaire est inférieur à cette réserve.

**L2 — La caméra reste un flux d'images espacées.** Le navigateur envoie une image JPEG 320 × 240 environ chaque seconde. C'est raisonnable pour limiter le débit, mais insuffisant pour certaines interactions visuelles rapides. Les futures options doivent contrôler la cadence, la résolution et la pause caméra depuis l'interface, tout en respectant les coûts et la confidentialité.

**L2 — Absence de recette E2E Live fournisseur.** `tests/test_live.py` vérifie la configuration, les blocs Base64, le calcul de consommation, le quota et le refus d'un token vide. Il ne valide pas un vrai cycle microphone → WebSocket → Gemini → audio navigateur sur Render. Le document `docs/PHASE_5_LIVE.md` indique également que cette recette réelle n'a pas été effectuée.

## 2. Mode Work

### Architecture actuelle observée

- Interface : `app/workspace.js` et `app/workspace.css`.
- Point d'entrée agent : `POST /api/work/agent`, déclaré dans `llink_api/api/routes/agent.py`.
- Flux : Server-Sent Events ; les événements décrivent le plan, le démarrage et la fin des tours modèle, les appels d'outils, les résultats, la progression de documents et le résultat final.
- Protocole : appels de fonctions natifs, version `native-functions-v1`.
- Limites agent : 36 tours modèle, 48 appels d'outils, 360 secondes par tâche, 12 000 caractères par résultat d'outil, livrable jusqu'à 8 Mo.
- Pièces jointes agent : jusqu'à 12 images, 6 Mo par image ; l'interface limite les fichiers joints à 5 et le volume combiné à 25 Mo.
- Le modèle, le niveau d'abonnement et l'effort de réflexion sont transmis à l'agent ; le backend résout le fournisseur, vérifie les droits et contrôle les clés API.
- Les outils couvrent notamment la recherche Web, l'ouverture de pages, les images, Python, les documents, les fichiers et projets Work, ainsi qu'un environnement de développement isolé E2B lorsque configuré.

### Stockage et édition

- Les projets et fichiers texte cloud sont stockés dans les sous-collections Firestore de chaque utilisateur.
- Limites déclarées dans `llink_api/api/routes/work.py` : 100 projets, 500 fichiers, 700 Ko maximum par fichier texte et 20 versions conservées.
- Les mises à jour texte utilisent un numéro de version attendu afin de détecter les modifications concurrentes.
- Le frontend conserve les projets, messages et fichiers dans IndexedDB pour travailler localement.
- Les éditeurs locaux couvrent notamment DOCX, XLSX, PPTX, PDF et images ; les fichiers binaires peuvent atteindre 50 Mo dans le stockage local, avec une limite d'import de 10 Mo par fichier.

### Problèmes et améliorations prioritaires

**W1 — Les fichiers binaires ne sont pas synchronisés vers le cloud.** La fonction frontend `syncFile()` retourne immédiatement pour les fichiers binaires ; `saveFile()` enregistre ces fichiers dans IndexedDB et affiche explicitement que la connexion au serveur sera ajoutée séparément. Après changement d'appareil ou perte du stockage navigateur, le fichier binaire local n'est donc pas restauré depuis Work.  
À faire : ajouter un stockage objet sécurisé (par exemple un bucket privé) avec métadonnées Firestore, contrôle de propriété, URL signées, versionnement et reprise des transferts. Les contenus binaires ne doivent pas être injectés dans les documents Firestore.

**W1 — Le contexte de conversation envoyé à chaque tâche est borné.** Le frontend transmet les 12 derniers messages précédents, avec une limite de 8 000 caractères par message. L'historique local est plus long, mais une tâche éloignée peut perdre des décisions ou contraintes anciennes si elles ne figurent plus dans ces 12 messages.  
À faire : introduire un résumé de projet durable, les objectifs, décisions, fichiers de référence, état de la tâche et critères d'acceptation ; construire un contexte compact au lieu de dépendre uniquement des derniers messages.

**W1 — La persistance de l'environnement de code est limitée à la tâche.** Les sessions E2B sont fermées dans le bloc `finally` de l'agent. Le sandbox peut synchroniser un ensemble limité de fichiers validés, mais n'est pas un environnement qui persiste entre les tâches.  
À faire : conserver l'état du projet dans le workspace cloud et rouvrir un sandbox à partir de cet état ; présenter les changements avant synchronisation et garder un diff/rollback par fichier.

**W2 — Dépendance Firestore.** Les routes projets/fichiers renvoient une indisponibilité si Firestore n'est pas configuré. Le stockage local fonctionne, mais la partie cloud Work n'est pas autonome sans ce service. Le modèle de données, les règles d'accès et les sauvegardes doivent être considérés comme une dépendance de production.

**W2 — Quotas d'outils distincts.** Les routes de lecture, écriture, suppression et exécution d'outils appliquent leurs propres quotas. Il faut afficher à l'utilisateur les limites et les erreurs de quota sous une forme explicite plutôt qu'un échec générique de tâche.

**W2 — Vérification du livrable.** Le backend dispose déjà de contrôles de qualité pour les documents et ne remet pas un artefact marqué non vérifié. Il faut étendre cette discipline à tous les formats : réouverture du fichier, contrôle du MIME/type, validation du contenu, taille, intégrité ZIP pour Office, et vérification indépendante des résultats de code.

## 3. Plan d'amélioration proposé

### Priorité 0 — Fiabilité de la boucle de base
1. Valider en navigateur le nouvel écran Live audio, la session WebSocket, les interruptions et le passage audio ↔ vidéo sans déconnexion.
2. Exécuter les tests backend et Playwright sur la branche.
3. Confirmer avec une session Gemini réelle la compression du contexte, le relevé des tokens et la libération de la réserve de coût.
4. Ajouter une recette E2E Live avec microphone simulé, permission refusée, coupure réseau et fermeture propre.

### Priorité 1 — Continuité et latence Live
1. AudioWorklet et blocs de 20–40 ms.
2. GoAway, session resumption et reconnexion.
3. Budgets prévisionnels adaptés à la durée et aux modalités.
4. Gestion de la qualité caméra, du réseau instable et de la reprise après perte de WebSocket.

### Priorité 1 — Fiabilité Work
1. Service de stockage objet pour les fichiers binaires.
2. Résumé de projet et mémoire de tâche structurée.
3. Environnement de code rouvrable à partir des fichiers cloud.
4. Synchronisation avec conflits visibles, diff, restauration et sauvegarde.

### Priorité 2 — Expérience unifiée
1. Afficher un état d'activité commun : connexion, écoute, réponse, outil en cours, fichier modifié, sauvegarde en attente et erreur.
2. Réutiliser les mêmes conversations et le même contexte de projet quand l'utilisateur passe de Chat à Work ou de Live audio à Live vidéo.
3. Prévoir un panneau de diagnostic non technique avec détails repliables pour les erreurs fournisseur, quota, permission média et synchronisation.

## 4. Références officielles Live consultées

- Session management : https://ai.google.dev/gemini-api/docs/live-api/session-management
- Best practices : https://ai.google.dev/gemini-api/docs/live-api/best-practices
- Send audio and video streams : https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/send-audio-video-streams
- Troubleshooting : https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/live-api/troubleshooting

## Conclusion

Work a déjà une base d'agent exploitable ; il faut maintenant garantir la continuité du contexte et la synchronisation réelle de tous les fichiers. Live a une bonne base de transport audio/vidéo et de contrôle d'accès ; ses priorités sont le mode vocal commun, la latence audio, la reprise de session et un budget de départ mieux calibré.

L'interface mise à jour doit être validée visuellement et fonctionnellement avant fusion sur `main`.