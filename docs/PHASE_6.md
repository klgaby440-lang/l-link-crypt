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
- La génération d'images originales n'est pas encore reliée à un fournisseur dans Work.
- Les formats structurés pris en charge par le nouveau moteur sont DOCX ; PDF et XLSX utilisent encore le convertisseur de contenu existant.
