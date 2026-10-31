# Llink — CRYPT

Llink is the CRYPT AI application.

## Project layout

- `main.py`: stable FastAPI entry point (`uvicorn main:app`).
- `llink_api/`: modular backend, routes, providers, services, schemas, database and security.
- `app/index.html`: canonical web application.
- `capacitor/`: Capacitor 8 project and Android wrapper.
- `docs/API_CONTRACTS.md`: HTTP contracts used by the current frontend.
- `docs/API_SECURITY.md`: environment variables, quotas and access rules.
- `docs/PHASE_1.md`, `docs/PHASE_2.md`: implementation notes and release boundaries.

The Capacitor project uses `../app` as its web directory. There is no separate `www/index.html` copy.

## Android build

Requirements: Node.js 22+, Java 21, Android SDK.

```bash
cd capacitor
npm ci
# First-time setup only:
npx cap add android
npx cap sync android
cd android
./gradlew assembleDebug
```

The GitHub Actions workflow `.github/workflows/android-build.yml` builds the Android debug APK and publishes it as a workflow artifact.

## Backend

Install production dependencies:

```bash
python -m pip install -r requirements.txt
uvicorn main:app --reload
```

Install test dependencies and run the suite:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

### Production configuration

Configure `APP_ENV=production`, `FIREBASE_CONFIG`, `GEMINI_API_KEY`, `HF_TOKEN` and `CORS_ORIGINS` through Render environment variables. Llink fails closed for metered AI routes if Firestore cannot enforce the quota ledger.

Read [docs/API_SECURITY.md](docs/API_SECURITY.md) before deploying changes to the backend.

Never commit real `.env` files, API tokens, service-account JSON files, or private keys.
