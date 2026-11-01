# Phase 5 — Capacités multimodales

Branche : \`phase-5/multimodal-foundation\`

## Objectif du premier lot

Permettre de joindre plusieurs fichiers directement depuis le compositeur Llink, les afficher avant envoi, puis transmettre leur contenu au backend selon le type réel du fichier. Le chat reste compatible avec les appels JSON existants.

## Contrat initial des pièces jointes

- \`POST /api/chat/attachments\` reçoit un formulaire multipart avec \`message\`, \`history\`, \`model\`, \`level\`, \`effort\`, \`mode\`, \`preferences\`, \`source\` et plusieurs champs \`files\`.
- Jusqu'à 5 fichiers par message.
- 10 Mo maximum par fichier et 25 Mo au total par message (valeurs configurables).
- Taille HTTP par défaut : 27 Mo afin de laisser une marge au multipart.
- PDF, JPEG, PNG, WebP, BMP, GIF, TIFF, HEIC, HEIF, audio et vidéo (MP4, MOV, WebM, MPEG/MPG, AVI, WMV, FLV et 3GP) sont analysés par Gemini 3.5 Flash-Lite, puis leur synthèse est transmise au modèle sélectionné dans Llink.
- TXT, Markdown, CSV, JSON, XML, HTML, fichiers de code, DOCX, XLSX et PPTX sont extraits côté serveur et inclus dans le contexte.
- Tout fichier sélectionné est reçu comme pièce jointe. Les formats binaires sans extracteur sont affichés avec leur nom et leur type, mais Llink indique clairement qu'il n'a pas pu en lire le contenu.

## Traduction

- Le mode `translate` transmet les codes de langue source et cible choisis dans l'interface.
- Les codes sont validés côté backend puis intégrés à l'instruction système du traducteur.
- La traduction conserve autant que possible le sens, le ton, les liens et la mise en forme ; le mode de traduction s'applique également au contenu extrait des pièces jointes.
- La sélection d'une source `auto` permet la détection de la langue d'origine.

## Sécurité et coût

- Le nom de fichier est réduit à un nom simple ; les chemins envoyés par le client ne sont jamais conservés.
- Les octets sont lus avec des limites, puis contrôlés avec des signatures pour images, PDF et formats vidéo identifiables. BMP, GIF (première image) et TIFF sont convertis en PNG avec une limite de pixels ; HEIC/HEIF sont conservés pour Gemini.
- Les archives Office sont plafonnées en nombre d'entrées et en taille décompressée ; aucun contenu Office n'est exécuté.
- L'analyse multimodale est protégée par un quota spécifique et un créneau de concurrence.
- L'appel Gemini d'analyse utilise la tarification du registre VELORA pour calculer la dépense réelle, mais l'impute au niveau de l'utilisateur qui a initié le chat. Le chat final garde sa propre mesure d'usage.
- Le contexte extrait reste borné par la limite de message déjà appliquée par le chat.
- Les contenus multimédias en ligne sont plafonnés à 18 Mo au total pour l'envoi inline à Gemini.

## Limites explicites du premier lot

- « Accepter tout fichier » signifie que le sélecteur accepte n'importe quelle extension ; cela ne signifie pas qu'un modèle peut interpréter arbitrairement chaque format binaire.
- Les formats non pris en charge restent visibles et nommés, mais ne sont pas prétendus analysés.
- L'analyse des fichiers nécessite une connexion et une clé Gemini configurée.
- Les fichiers ne sont pas envoyés automatiquement à un fournisseur tiers sans action d'envoi de l'utilisateur.
- Les fichiers originaux ne sont pas conservés dans Firestore ; les conversations sauvegardent la métadonnée d'attachement, pas le binaire.
- La voix bidirectionnelle temps réel, la génération vocale serveur, les codecs spécialisés et l'analyse vidéo en direct restent des sous-lots à valider séparément.

## Validation

Les tests couvrent la classification, l'extraction bureautique et texte, les signatures, les limites, l'accès et le passage du contexte aux routes de chat. Une recette avec les vraies clés Gemini et des fichiers représentatifs reste indispensable avant déploiement.
