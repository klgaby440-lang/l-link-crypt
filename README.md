# Llink — CRYPT

Llink est l'application d'assistance IA de CRYPT.

## Structure du dépôt

- `main.py` : point d'entrée FastAPI stable (`uvicorn main:app`).
- `llink_api/` : backend modulaire, routes, fournisseurs, services, schémas et sécurité.
- `app/index.html` : application web canonique.
- `capacitor/` : projet Capacitor 8 et wrapper Android.
- `desktop/src-tauri/` : application de bureau Tauri v2.
- `desktop/installer/Llink.iss` : programme d'installation Windows Inno Setup.
- `build-tools/package.json` : dépendances de compilation des ressources locales.
- `scripts/prepare-offline-assets.mjs` : préparation du modèle ONNX, Transformers.js, ONNX Runtime, Firebase, Tesseract et ressources linguistiques.
- `docs/OFFLINE_NATIVE_BUILD_REPORT_20261107.md` : rapport de livraison, limites et plan de validation.

## Mode hors ligne

Le premier mode hors ligne est limité au **Chat** et au modèle **SmolLM-135M-Instruct ONNX Q4**. Il fonctionne seulement dans l'APK Android Capacitor ou le logiciel Windows Tauri avec un compte Firebase connecté via Google (`google.com`). L'application Web reste en ligne uniquement. Work et Live restent en ligne dans cette version ; l'OCR local avec Tesseract est disponible dans les applications natives sous la même condition de connexion Google.

Les fichiers du modèle (environ 181 Mo pour ONNX Q4), les bibliothèques, les fichiers WASM et les données Tesseract sont téléchargés et intégrés pendant le build. Ils ne sont pas commités dans Git. Les workflows publient des artefacts GitHub Actions conservés 14 jours.

## Préparation des ressources hors ligne

Prérequis : Node.js 22+.

```bash
npm --prefix build-tools install --no-audit --no-fund
node scripts/prepare-offline-assets.mjs
./build-tools/node_modules/.bin/tailwindcss -c tailwind.config.cjs -i scripts/tailwind.input.css -o app/vendor/tailwind.min.css --minify
```

Pour préparer les dépendances d'interface sans télécharger le modèle (tests Playwright) :

```bash
node scripts/prepare-offline-assets.mjs --skip-model
```

## Build Android

Prérequis : Node.js 22+, Java 21 et Android SDK 36.

```bash
cd capacitor
npm ci
npx cap add android  # seulement si capacitor/android n'existe pas
npx cap sync android
cd android
./gradlew assembleDebug
```

Le workflow `.github/workflows/android-build.yml` exécute la préparation des modèles, synchronise Capacitor, compile l'APK et téléverse l'artefact.

## Build Windows (Tauri + Inno Setup)

Prérequis : Node.js 22+, Rust stable, Visual Studio C++ Build Tools et Inno Setup 6.

```bash
npm --prefix build-tools install --no-audit --no-fund
node scripts/prepare-offline-assets.mjs
./build-tools/node_modules/.bin/tailwindcss -c tailwind.config.cjs -i scripts/tailwind.input.css -o app/vendor/tailwind.min.css --minify
cd desktop
npm install
npx tauri build --config src-tauri/tauri.conf.json
```

Puis compiler `desktop/installer/Llink.iss` avec Inno Setup 6. Le workflow `.github/workflows/windows-desktop-build.yml` construit les artefacts Tauri et Inno Setup.

## Backend

```bash
python -m pip install -r requirements.txt
uvicorn main:app --reload
```

Tests :

```bash
python -m pip install -r requirements-dev.txt
APP_ENV=test python -m pytest -q
```

## Configuration de production

Configurer via les variables d'environnement Render : `APP_ENV=production`, `FIREBASE_CONFIG`, `GEMINI_API_KEY`, `ZAI_API_KEY`, `MINIMAX_API_KEY`, `DEEPSEEK_API_KEY`, `HF_TOKEN` et `CORS_ORIGINS`.

La génération d'image Work utilise GLM-Image et nécessite `ZAI_API_KEY` côté serveur, un compte authentifié et les quotas Work disponibles. Dans le registre actuel, cette capacité n'est pas réservée à un niveau de formule particulier.

Les plafonds monétaires horaires facultatifs utilisent `LLINK_HOURLY_CREDIT_LIMITS_USD`. Lire [API_SECURITY.md](docs/API_SECURITY.md) et [PHASE_3.md](docs/PHASE_3.md) avant tout changement de production.

Ne jamais committer de fichier `.env`, de token, de compte de service ou de clé privée.
