# Rapport de livraison — Llink natif, chat hors ligne et génération d'images Work

Date : 7 novembre 2026
Branche de travail : `feature/work-live-interface-refresh-20261107`
Base de la branche : commit de l'interface Work/Live (PR #17)

## 1. Objectif

Préparer des applications Llink installées (Android et Windows) capables de proposer un premier Chat local avec SmolLM-135M-Instruct au format ONNX, via Transformers.js. Le mode hors ligne est limité au mode Chat et soumis à deux conditions simultanées :
1. Llink est lancé depuis une application installée Capacitor Android ou Tauri Windows.
2. L'utilisateur possède une session Firebase dont les fournisseurs de connexion incluent Google (`google.com`).

Le site Web reste en ligne uniquement. Le mode Work hors ligne et le Live hors ligne ne font pas partie de cette première étape.

## 2. Changements intégrés dans la branche

### 2.1 Chat local SmolLM
- Suppression de l'ancien prototype `@xenova/transformers` chargé depuis un CDN.
- Ajout d'un moteur local `app/offline-engine.js`.
- Modèle choisi : `onnx-community/SmolLM-135M-Instruct-ONNX`, quantification Q4, fichier `onnx/model_q4.onnx`.
- Le pipeline reçoit jusqu'à 8 messages récents, bornés en taille pour limiter la mémoire.
- Maximum de génération fixé à 160 tokens pour ce test initial.
- Un seul pipeline local est chargé et réutilisé durant la session ; fonction de libération manuelle disponible.
- Le dispatch hors ligne est limité au mode Chat ; Work, Live et les autres modes affichent qu'une connexion est nécessaire.

### 2.2 Authentification et plateforme
- Vérification au moment de chaque génération : Capacitor Android ou Tauri, et compte Firebase lié au fournisseur Google.
- La disponibilité hors ligne est indépendante du forfait cloud.
- Le site Web ne peut pas satisfaire le contrôle de plateforme, même avec un compte Google.
- Le basculement réseau s'appuie sur `navigator.onLine` et sur les événements `online` / `offline`.
- Les bibliothèques web essentielles (Firebase, Dexie, Lucide, Marked, DOMPurify, Tailwind) sont préparées localement afin d'éviter les CDN au démarrage de la version installée.

### 2.3 OCR
- Ajout du bundling local de Tesseract.js et de son worker.
- Ajout du moteur WASM de Tesseract et des fichiers linguistiques français et anglais.
- Le parcours OCR local vérifie la même condition application installée + compte Google.
- Limite fonctionnelle : Tesseract extrait le texte d'une image ; ce n'est pas un modèle de vision capable d'interpréter des éléments non textuels.

### 2.4 Work — génération d'images
- Le backend de la branche contient déjà l'outil natif `image_generate`, appelé avec GLM-Image via `ZAI_API_KEY`.
- Le PNG produit devient un artefact Work et doit être soumis à `artifact_verify` avant livraison.
- Ajout d'une action visible « Générer une image » dans l'en-tête Work, uniquement si `/api/work/agent/status` annonce réellement `image_generate`.
- L'outil est déclaré pour les utilisateurs authentifiés indépendamment du niveau de formule. Les limites techniques et quotas globaux Work s'appliquent toujours ; une clé `ZAI_API_KEY` valide reste nécessaire.

### 2.5 Capacitor Android
- Workflow Android ajusté pour s'exécuter également sur `feature/**` et sur les pull requests.
- Le workflow prépare les dépendances, modèles, workers, fichiers WASM, langues OCR et CSS avant `npx cap sync android`.
- Compilation configurée avec Node.js 22, Java 21 et Android SDK 36.
- L'artefact prévu est un APK debug téléchargeable depuis GitHub Actions.

### 2.6 Tauri et Inno Setup Windows
- Nouveau projet Tauri v2 sous `desktop/src-tauri`, avec la même application web et les ressources locales embarquées.
- Tauri produit l'exécutable Windows avec l'option `--no-bundle` afin d'éviter une seconde compression/installation NSIS du modèle.
- Le programme d'installation final est produit par Inno Setup à partir de l'exécutable Tauri.
- Nouveau script Inno Setup `desktop/installer/Llink.iss` produisant `Llink-Setup.exe`.
- Nouveau workflow Windows x64 qui prépare les ressources, compile Tauri, installe Inno Setup et publie les artefacts.

### 2.7 Tests
- Ajout de tests Playwright pour vérifier :
  - refus du mode hors ligne sur le Web, même avec Google ;
  - refus dans Capacitor si le compte n'est pas lié à Google ;
  - autorisation théorique lorsque l'application native et Google sont présents.
- Ces tests valident la règle d'accès du frontend. Ils ne remplacent pas une connexion Google native réelle sur téléphone ou Windows.

## 3. Comportement attendu

| Environnement | Compte Google | Mode hors ligne |
|---|---|---|
| Site Web | Oui | Refusé |
| Site Web | Non | Refusé |
| APK Android | Non | Refusé |
| APK Android | Oui | Autorisé |
| Logiciel Tauri Windows | Non | Refusé |
| Logiciel Tauri Windows | Oui | Autorisé |

La génération locale ne passe pas par Render ni par Gemini. Après installation, le modèle, ONNX Runtime, les bibliothèques nécessaires et les ressources OCR sont fournis avec l'application.

## 4. Ce qui reste à faire ou à valider

### Bloquants avant de qualifier la livraison de « compilée et testée »
1. Exécuter les workflows GitHub Actions et confirmer la réussite réelle de l'APK, du build Tauri et de l'installateur Inno Setup.
2. Tester l'authentification Google dans les WebViews Capacitor et Tauri. Le flux actuel repose sur Firebase `signInWithPopup`; les fournisseurs OAuth peuvent refuser les WebViews intégrées. Si le flux ne passe pas, intégrer l'authentification Google native Capacitor/Tauri avec la configuration Firebase/Google du projet.
3. Installer l'APK sur un vrai téléphone, se connecter avec Google, activer le mode avion et vérifier le chat.
4. Installer le logiciel Windows, se connecter avec Google et refaire le test.
5. Mesurer mémoire, temps d'initialisation, tokens/seconde, température et stabilité après plusieurs conversations.
6. Vérifier que la génération SmolLM fonctionne sans aucune requête réseau après le démarrage initial de l'application.
7. Tester Tesseract en mode avion sur des photos prises avec différents téléphones.

### Améliorations importantes après le premier test
- Afficher la taille estimée et l'espace requis avant téléchargement/installation.
- Ajouter un test de ressources de l'appareil et un avertissement mémoire sur les petits téléphones.
- Remplacer les réponses synchrones par une génération progressive et prévoir l'annulation.
- Ajouter une stratégie de réduction du contexte et de libération du modèle quand la mémoire manque.
- Ajouter une autorisation hors ligne signée avec durée de validité si l'accès doit survivre à une expiration des jetons Firebase. Actuellement, l'accès repose sur l'utilisateur Firebase présent dans le stockage local de l'appareil.
- Ajouter une validation automatique des fichiers du modèle (taille, empreinte SHA-256) à l'installation et au démarrage.
- Envisager Android App Bundle / Play Asset Delivery si la taille finale APK dépasse les limites souhaitées pour la distribution publique.

### Limites fonctionnelles connues
- SmolLM-135M est un modèle de test compact ; ses réponses ne sont pas comparables aux modèles cloud.
- Le modèle n'est pas encore spécialisé par LoRA et ne connaît pas de manière fiable les programmes scolaires de RDC.
- Il n'y a pas d'agent Work local, de Live vocal local, de STT/TTS hors ligne ni de compréhension visuelle locale dans cette livraison.
- L'OCR local reconnaît le texte mais ne comprend pas une image comme un modèle vision.
- L'authentification Google dans les WebViews natives doit être testée sur les systèmes cibles avant de considérer la condition Google opérationnelle.

## 5. Reproduction des builds

Ressources :
```bash
npm --prefix build-tools install --no-audit --no-fund
node scripts/prepare-offline-assets.mjs
npx --yes tailwindcss@3.4.17 -c tailwind.config.cjs -i scripts/tailwind.input.css -o app/vendor/tailwind.min.css --minify
```

Android :
```bash
cd capacitor
npm ci
npx cap add android   # uniquement si le dossier android n'existe pas
npx cap sync android
cd android
./gradlew assembleDebug
```

Windows :
```bash
cd desktop
npm install
npx tauri build --config src-tauri/tauri.conf.json
```

Puis compiler `desktop/installer/Llink.iss` avec Inno Setup 6.

## 6. État de fusion et de livraison

- Branche de travail : `feature/work-live-interface-refresh-20261107`.
- PR #17 : fusionnée dans `main` le 7 novembre 2026 à 14:06 UTC.
- Commit de fusion : `f006f272c9344a85c2ee687d08b5a74a0ff02e16`.
- La branche `main` pointe maintenant sur ce commit.

### Résultats CI sur le dernier commit de fonctionnalité

- Tests backend : réussis.
- Tests Playwright interface / règles d'accès hors ligne : réussis.
- Build Android Capacitor debug : réussi.
- APK extrait, reconnu comme paquet Android et inspecté : le modèle ONNX Q4, Transformers.js, Firebase local, Tesseract et les données linguistiques FR/EN sont présents.
- Build Windows Tauri + Inno Setup : **en cours au dernier contrôle** ; aucun EXE ou installateur Windows n'est déclaré disponible tant que le workflow ne l'a pas publié.

### APK Android de test

- Fichier : `Llink-Android-offline.apk`.
- Taille : 163 319 783 octets.
- SHA-256 : `62588cadfb9ea3c797f94f74cc2a04eec600994f622e2cb3d59acc3711dcf0d5`.
- [Workflow Android et artefact GitHub Actions](https://github.com/klgaby440-lang/l-link-crypt/actions/runs/42379582748).

La fusion permet de poursuivre les essais sur `main`. Elle ne remplace pas la recette sur appareils physiques : connexion Google dans les WebViews, inférence réelle SmolLM sur téléphone/PC, OCR en mode avion, mémoire, chauffe et performances restent à tester.


## Mise à jour finale après compilation de `main`

Vérification effectuée sur `main` après fusion de la PR #17.

- Commit de fusion : `f006f272c9344a85c2ee687d08b5a74a0ff02e16`.
- Tête de `main` après mise à jour du rapport : `77e5e7fad1c08ffd2893df3d1d20df211edbde6d`.
- Tests backend : réussis sur `main` (run `42380053266`).
- Tests d'interface Playwright : réussis sur `main` (run `42380053415`).
- Build APK Android debug : réussi sur `main` (run `42380053580`).
- L'APK de ce run a été extrait et inspecté : il contient `model_q4.onnx` (180 581 125 octets), `offline-engine.js`, `transformers.min.js`, `firebase-runtime.js`, ainsi que `fra.traineddata` et `eng.traineddata`.
- APK : 163 319 783 octets. SHA-256 : `62588cadfb9ea3c797f94f74cc2a04eec600994f622e2cb3d59acc3711dcf0d5`.
- Build Windows : workflow `42380053277` toujours en cours à l'étape `Build Tauri Windows executable (Inno Setup creates the installer)` au dernier contrôle. Aucun EXE ni `Llink-Setup.exe` n'a encore été publié ; ne pas les considérer comme livrés.

Liens des validations sur `main` :
- [Workflow Android / APK](https://github.com/klgaby440-lang/l-link-crypt/actions/runs/42380053580)
- [Tests Playwright](https://github.com/klgaby440-lang/l-link-crypt/actions/runs/42380053415)
- [Tests backend](https://github.com/klgaby440-lang/l-link-crypt/actions/runs/42380053266)
- [Build Tauri + Inno Setup](https://github.com/klgaby440-lang/l-link-crypt/actions/runs/42380053277)

Ces résultats automatisés ne remplacent pas les tests physiques : OAuth Google dans les WebViews, inférence locale SmolLM en mode avion, OCR hors connexion, mesure mémoire et performances restent à effectuer sur les appareils cibles.
