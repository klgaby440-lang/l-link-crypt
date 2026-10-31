# Llink — CRYPT

Llink is the CRYPT AI application.

## Project layout

- `main.py`: stable FastAPI entry point (`uvicorn main:app`).
- `llink_api/`: modular backend, routes, providers, services, schemas, database and security.
- `app/index.html`: canonical web application.
- `capacitor/`: Capacitor 8 project and Android wrapper.
- `docs/API_CONTRACTS.md`: HTTP contracts used by the current frontend.
- `docs/PHASE_1.md`: implementation notes and boundaries for Phase 1.

The Capacitor project uses `../app` as its web directory. There is no separate `www/index.html` copy.

## Android build

Requirements: Node.js 22+, Java 21, Android SDK.

From the repository root:

```bash
cd capacitor
npm ci

# First-time setup only:
npx cap add android

# Copy app/index.html and synchronize native dependencies:
npx cap sync android

# Build a local debug APK:
cd android
./gradlew assembleDebug
```

The GitHub Actions workflow `.github/workflows/android-build.yml` builds the Android debug APK and publishes it as a workflow artifact.

## Backend

Install production dependencies:

```bash
python -m pip install -r requirements.txt
```

Run locally:

```bash
uvicorn main:app --reload
```

Install development/test dependencies and run the API contract tests:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Configure backend credentials through environment variables (for example on Render). Main settings are `FIREBASE_CONFIG`, `GEMINI_API_KEY`, `HF_TOKEN` and `CORS_ORIGINS`. Dataset collection is disabled unless both the server feature flag `ENABLE_DATASET_COLLECTION=true` and the per-request consent field `data_collection_consent=true` are present.

Never commit real `.env` files, API tokens, service-account JSON files, or private keys.
