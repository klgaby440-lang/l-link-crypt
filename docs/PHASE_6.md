# Phase 6 — Work et Tool Engine

## Objectif

Faire de Work un espace de travail persistant pour la rédaction, l'analyse, le code, les projets et les fichiers. Les opérations cloud sont toujours isolées par UID Firebase et exécutées côté serveur.

## Lot 6.1 — Workspace et fichiers

- Projets privés par utilisateur : création, lecture, modification et suppression.
- Fichiers texte privés par utilisateur : création, lecture, modification, suppression.
- Dossiers relatifs, chemin nettoyé et noms de fichiers validés.
- Versionnement serveur : sauvegarde du contenu précédent à chaque modification, restauration d'une version et limite de conservation à 20 versions.
- Contrôle optimiste de version : une modification envoyée avec une version obsolète retourne HTTP 409 plutôt que d'écraser silencieusement le travail récent.
- Limites : 500 fichiers et 100 projets par utilisateur ; 700 Ko maximum de texte UTF-8 par fichier.
- Quotas distincts pour lecture, écriture et suppression.
- Les routes cloud exigent une session Firebase vérifiée ; aucun accès anonyme au workspace cloud.

## Contrat API

- \`GET/POST /api/work/projects\`
- \`PATCH/DELETE /api/work/projects/{project_id}\`
- \`GET/POST /api/work/files\`
- \`GET/PUT/DELETE /api/work/files/{file_id}\`
- \`GET /api/work/files/{file_id}/versions\`
- \`POST /api/work/files/{file_id}/restore\`

Les documents sont stockés dans \`users/{uid}/work_projects\` et \`users/{uid}/work_files\`. Chaque fichier conserve ses révisions dans une sous-collection \`versions\`. Les ID fournis par le navigateur ne déterminent jamais l'UID de stockage ; celui-ci provient uniquement du jeton Firebase vérifié.

## Limites explicites

- Les premiers outils actifs sont projets/fichiers/versions. Aucun terminal arbitraire, accès shell, navigation web autonome ou exécution de programme n'est exposé à ce stade.
- Les fichiers binaires ne sont pas stockés dans les documents Firestore ; le stockage d'objets volumineux nécessitera un service de fichiers dédié avec URL signées, quotas et politique de rétention.
- La conversation Work peut préparer des modifications dans l'éditeur ; l'utilisateur conserve la décision d'appliquer puis de sauvegarder le résultat.
- L'édition locale doit continuer de fonctionner sans réseau ; la synchronisation cloud dépend de Firebase/Firestore et d'une connexion.

## Validation

- Tests sur validation des chemins et tailles.
- Tests d'accès prouvant que les routes Work cloud refusent les sessions anonymes.
- Tests d'intégration Firestore et tests navigateur encore requis avant d'annoncer le lot comme validé.


## Extension — moteur documentaire et orchestration Work

- Le registre `GET /api/work/tools` expose les capacités non sensibles même sans session : export PDF/XLSX et création DOCX structurée. Les disponibilités Web/Python ne sont déclarées que si leurs clés serveur sont configurées.
- `POST /api/work/tools/document` génère un vrai DOCX à partir de blocs contrôlés : titres, paragraphes, listes, citations, tableaux, sauts de page, légendes et images PNG/JPEG transmises sous forme de data URL.
- La recherche d'images utilise Tavily (clé `TAVILY_API_KEY`). Les images sont téléchargées après contrôle d'URL, de type, de taille et de résolution, puis intégrées au DOCX via un identifiant interne. La source de chaque image est ajoutée en légende. Les licences de réutilisation ne sont pas automatiquement vérifiées ; elles doivent être contrôlées avant publication. La génération d'images originales n'est pas encore intégrée.
- Les exports de documents sans données privées sont accessibles à l'utilisateur anonyme avec quota par adresse IP. Les outils Web Search et Python restent réservés aux sessions Firebase authentifiées.
- Le mode Work passe par `POST /api/work/agent` (ou par `/api/chat/attachments` après extraction des pièces jointes). Le serveur appelle les fonctions natives des modèles compatibles OpenAI et Gemini, exécute une boucle bornée à 12 tours de modèle et 20 appels d'outils maximum, puis diffuse les événements SSE `plan`, `tool_start`, `tool_result`, `final` et `error`.
- Les outils incluent `web_search`, `web_open`, `image_search`, `python`, `document_begin`, `document_add_blocks`, `document_finalize`, `artifact_verify`, `create_text_file` et `export_file`. Les documents Word sont écrits par sections et par lots de six blocs maximum.
- La livraison d'un fichier est bloquée tant que `artifact_verify` n'a pas rouvert le fichier et validé sa structure. Les documents binaires livrés sont enregistrés dans IndexedDB local et proposés au téléchargement.

### Limites restantes

- Les documents binaires créés sont conservés localement dans IndexedDB ; ils ne sont pas encore synchronisés vers un stockage cloud d'objets.
- La génération d'images originales utilise GLM-Image via `ZAI_API_KEY`. Les fichiers PNG générés sont stockés comme artefacts temporaires, insérables par `image_id`, puis relus par Pillow avant leur livraison. La clé Z.AI doit être configurée sur Render.
- Les formats structurés pris en charge par le nouveau moteur sont DOCX ; PDF et XLSX utilisent encore le convertisseur de contenu existant.

## Extension — Agent Work natif généraliste et contrôle des livrables

Le mode Work utilise désormais un orchestrateur serveur dédié (llink_api/services/work_agent.py) et la route POST /api/work/agent. Le client vérifie d'abord GET /api/work/agent/status, qui retourne la version du protocole, les outils réellement actifs pour la session et les limites d'exécution. Le protocole courant est native-functions-v1 ; l'interface refuse d'envoyer une tâche à un backend qui expose encore l'ancien protocole textuel.

### Boucle d'agent

- Le modèle reçoit les schémas de fonctions natifs du fournisseur, choisit ses outils et renvoie des arguments structurés.
- L'orchestrateur exécute les fonctions dans le serveur, renvoie leurs résultats au modèle et poursuit jusqu'à une réponse finale ou une limite de sécurité.
- Budget maximal par tâche : 24 tours du modèle, 32 appels d'outils et 240 secondes.
- Les messages d'assistant des fournisseurs compatibles sont conservés tels quels entre les tours, notamment reasoning_content lorsque le fournisseur l'exige.
- Work utilise Extra par défaut si l'utilisateur n'a jamais réglé l'intensité ; une préférence enregistrée Normal, Extra ou Ultime est respectée.
- Le panneau Work expose le plan, les critères de réussite, les décisions résumées, les outils exécutés et leurs résultats confirmés. Il ne révèle pas de chaîne de pensée interne privée.

### Outils disponibles

Le registre natif comprend la mise à jour du plan, la recherche et l'ouverture de sources Web, la recherche d'images, la génération d'images, Python isolé, la rédaction DOCX en lots, l'export PDF/XLSX, la création de fichiers texte et la vérification d'artefacts. Les outils distants ne sont annoncés que lorsque les clés serveur et l'authentification nécessaires sont présentes.

### Critères de réussite et contrôle documentaire

- Les demandes de documents peuvent déclarer un contrat de qualité : minimum de mots, images, tableaux, URL de sources, titres obligatoires et bibliographie.
- Le serveur infère également certains critères depuis la demande. Un document demandé en cinq pages vise au moins 1 500 mots (approximation de contenu, pas une pagination calculée par moteur de rendu). Une demande de recherche impose au moins trois URL et une bibliographie.
- Les critères inférés sont des planchers : le modèle peut les renforcer, mais pas les réduire.
- Le moteur rouvre le DOCX généré et vérifie le texte, les tableaux, les images, les titres, le volume, les URL et la présence de la bibliographie.
- Un artefact ne peut être remis que si artifact_verify a réussi. Lorsqu'un fichier est explicitement demandé, l'agent ne peut pas annoncer sa livraison si aucun artefact vérifié n'existe.

### Version du frontend et compatibilité du backend

Le client ajoute un paramètre de version aux ressources Work pour éviter de conserver l'ancien JavaScript en cache. Il contrôle le protocole natif avant chaque tâche. Si Render n'a pas encore déployé le backend correspondant, Work affiche une erreur explicite et n'envoie pas la tâche à l'ancien endpoint.

### Limites opérationnelles

- La recherche Web et d'images dépend de TAVILY_API_KEY ; Python isolé dépend de E2B_API_KEY ; la génération d'images dépend de ZAI_API_KEY.
- Les fichiers générés sont renvoyés au navigateur et conservés dans l'espace de travail local. Une synchronisation cloud durable des binaires reste une évolution séparée.
- Les contrôles de qualité documentaires vérifient le contenu et la structure du DOCX. Le seuil de mots pour estimer cinq pages n'est pas un rendu paginé réel ; un contrôle visuel via un moteur DOCX vers PDF devra compléter cette vérification pour garantir une pagination exacte.
- Les tests CI valident les appels natifs simulés, les boucles multi-tours, les critères de qualité et les livraisons. Ils ne remplacent pas un essai en direct des clés et quotas de chaque fournisseur IA sur Render.

## Extension — Terminal de projet isolé et reprise documentaire

- Les outils `project_sandbox_open`, `project_run`, `project_list_files`, `project_read_file` et `project_sync_files` donnent à Work un véritable terminal Linux isolé E2B pour les projets authentifiés.
- Le sandbox copie au maximum 30 fichiers texte sélectionnés, avec une limite totale de 2 Mo. Les secrets et répertoires sensibles (.env, clés privées, certificats, .git, node_modules, caches et environnements virtuels) sont exclus.
- L'accès réseau est désactivé par défaut. Il ne peut être activé que lorsqu'une installation de dépendances le justifie. Aucun jeton Llink, secret fournisseur ou credential Firebase n'est transmis au sandbox.
- Les commandes ont une durée maximale de 60 secondes et leurs sorties sont tronquées à 10 000 caractères. Le sandbox est détruit à la fin de la tâche Work.
- Les fichiers modifiés ne sont pas synchronisés automatiquement. L'agent doit sélectionner explicitement les chemins après inspection et tests ; la synchronisation utilise les versions Firestore pour détecter les modifications concurrentes. Aucun outil de suppression n'est exposé.
- Une erreur de test est renvoyée comme un résultat structuré (code de sortie, stdout, stderr) afin que l'agent puisse diagnostiquer, corriger et relancer.
- Les limites maximales par tâche sont de 36 tours du modèle, 48 appels d'outils et 360 secondes. Elles restent bornées et soumises au budget d'utilisation du compte.
- Si un contrôle DOCX échoue, `artifact_verify` renvoie les critères manquants et les instructions de réparation. `document_begin` reprend le brouillon non vérifié du même nom par défaut. Un ancien artefact n'est marqué comme remplacé qu'après vérification réussie de la nouvelle version.
- Le terminal exige `E2B_API_KEY` sur Render. Les tests simulés vérifient le contrat logiciel ; un essai avec cette clé réelle reste nécessaire pour confirmer la configuration, les limites et la facturation E2B.

## Extension — navigation Web multipage textuelle

- `web_open` extrait désormais le véritable titre de la page, son texte lisible et jusqu'à 20 liens directs HTTP(S) pertinents.
- L'agent peut ouvrir les liens retournés par une page avec de nouveaux appels `web_open`, notamment pour suivre une documentation officielle, une référence ou une source citée.
- Les liens relatifs sont résolus par rapport à l'URL de la page. Les fragments sont retirés, les doublons et schémas dangereux (`javascript:`, `mailto:`, etc.) sont ignorés.
- Chaque nouvelle URL est soumise à la validation des hôtes publics avant ouverture ; les URL locales et réseaux privés restent refusés.
- Cette navigation est textuelle et non interactive : aucun JavaScript n'est exécuté, aucun compte n'est connecté, aucun formulaire ni bouton n'est activé et aucun fichier arbitraire n'est téléchargé. Les redirections HTTP doivent être recherchées puis ouvertes explicitement.


## Extension — édition locale des classeurs Excel

- Les fichiers `.xlsx` importés dans Work ouvrent un éditeur de grille basé sur SheetJS CE 0.20.3 (chargement à la demande depuis le CDN officiel).
- L'éditeur expose la sélection des feuilles, l'ajout de lignes/colonnes/feuilles, la modification des cellules et l'export d'un nouveau classeur XLSX.
- Les formules existantes sont présentées comme des formules et conservées comme expressions. Le moteur ne calcule pas les formules dans le navigateur ; le classeur exporté demande à Excel ou à un autre tableur compatible de recalculer à l'ouverture.
- Pour garder l'interface réactive, l'affichage est limité à 100 lignes et 40 colonnes visibles à la fois, avec pagination verticale.
- Les sauvegardes créent des versions locales dans IndexedDB. La restauration et l'export sont disponibles.
- Cette première édition est réservée au format `.xlsx`, fonctionne localement et ne synchronise pas les binaires vers Firestore. Les fichiers `.xls`, `.xlsm`, `.ods` et les fonctions avancées de mise en page/objets Excel ne sont pas garantis.
- Le test Playwright vérifie l'ouverture d'un classeur à deux feuilles, l'édition d'une valeur, la conservation d'une formule et la restauration d'une version.
